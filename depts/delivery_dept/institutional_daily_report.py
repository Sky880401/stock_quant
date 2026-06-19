from __future__ import annotations

"""法人日報藍圖骨架：prefer #106 / fallback #201。

本模組只提供可測試的最小閉環，不直接部署 #106。用途：
1. #106 producer 產出 JSON 成品（可由別處呼叫 build_preferred_106_payload）。
2. 18:00-18:10 驗證 contract/schema/health/freshness。
3. 驗證失敗時，自動 fallback 到 #201。
4. 18:30 前一定挑出一份可交付成品並寫出 delivery manifest。

設計原則（嚴謹度）：
- contract：來源槽位與 payload 宣告的 source_job_id 必須相符（#106 槽不能塞 #201 成品）。
- schema：列欄位不只檢查「有沒有」，還檢查型別、空字串、重複 stock_id、bool 偽裝數字。
- health：health.status 必須是已知狀態，red 直接判不可交付。
- freshness：data_date / generated_at 必須是當日，且 generated_at 不得是未來。
- manifest：寫出 checksum、deadline 合規旗標、每個候選來源的稽核軌跡。
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Iterable

SCHEDULE = {
    "preferred_106_produce": "17:30",
    "fallback_201_fetch": "17:45",
    "validation_window_start": "18:00",
    "validation_window_end": "18:10",
    "delivery_deadline": "18:30",
}

# 排程關鍵時刻（與 SCHEDULE 字串對應，供程式比較用，避免重複解析字串）。
DELIVERY_DEADLINE = time(18, 30)
VALIDATION_WINDOW_START = time(18, 0)
VALIDATION_WINDOW_END = time(18, 10)

REQUIRED_META_FIELDS = (
    "schema_version",
    "report_type",
    "source_job_id",
    "data_date",
    "generated_at",
    "health",
    "rows",
)
REQUIRED_ROW_FIELDS = ("stock_id", "foreign", "trust", "dealer", "total_balance")
NUMERIC_ROW_FIELDS = ("foreign", "trust", "dealer", "total_balance")
ALLOWED_SOURCE_JOB_IDS = {"106", "201"}
ALLOWED_HEALTH_STATUSES = {"green", "yellow", "red"}
# red 視為不可交付；green/yellow 可交付（yellow 代表降級但仍可用）。
BLOCKING_HEALTH_STATUSES = {"red"}
REPORT_TYPE = "institutional_daily_report"
SCHEMA_VERSION = "1.0"
MANIFEST_SCHEMA_VERSION = "1.0"

# generated_at 容許的未來時鐘偏移（跨機時鐘不同步時的緩衝）。
DEFAULT_FUTURE_SKEW = timedelta(minutes=5)


class ReportValidationError(ValueError):
    """法人日報 contract/schema/health/freshness 驗證失敗。"""


@dataclass(frozen=True)
class ValidationResult:
    source_job_id: str
    data_date: str
    row_count: int
    generated_at: str
    health_status: str


@dataclass(frozen=True)
class DeliveryDecision:
    selected_source_job_id: str
    selected_payload_path: str
    selected_data_date: str
    fallback_triggered: bool
    delivery_payload_path: str
    manifest_path: str
    health_status: str
    delivered_within_deadline: bool


def _iso_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _iso_datetime(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    return str(value)


def _coerce_path(path: str | Path) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _is_real_number(value: Any) -> bool:
    # bool 是 int 的子類，但法人買賣超欄位不該是 True/False，必須排除。
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_preferred_106_payload(
    *,
    data_date: date | str,
    rows: Iterable[dict[str, Any]],
    generated_at: datetime | str | None = None,
    health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generated = generated_at or datetime.now().replace(microsecond=0)
    row_list = [dict(row) for row in rows]
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "source_job_id": "106",
        "data_date": _iso_date(data_date),
        "generated_at": _iso_datetime(generated),
        "health": health or {"status": "green", "checks": ["schema", "freshness"]},
        "rows": row_list,
    }


def write_payload(path: str | Path, payload: dict[str, Any]) -> Path:
    target = _coerce_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def load_payload(path: str | Path) -> dict[str, Any]:
    return json.loads(_coerce_path(path).read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def validate_payload(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    expected_source_job_id: str | None = None,
    expected_data_date: date | str | None = None,
    future_skew: timedelta = DEFAULT_FUTURE_SKEW,
) -> ValidationResult:
    """驗證單一 payload 的 contract / schema / health / freshness。

    expected_source_job_id：若指定，payload 宣告的來源必須相符（槽位 contract）。
    expected_data_date：若指定，data_date 必須等於它；否則預設用 now.date()（當日）。
    """
    if not isinstance(payload, dict):
        raise ReportValidationError("payload 必須是 object")

    # --- contract: 必要 meta 欄位 ---
    for field in REQUIRED_META_FIELDS:
        if field not in payload:
            raise ReportValidationError(f"缺少必要欄位: {field}")

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ReportValidationError(f"schema_version 必須為 {SCHEMA_VERSION}")
    if payload.get("report_type") != REPORT_TYPE:
        raise ReportValidationError(f"report_type 必須為 {REPORT_TYPE}")

    source_job_id = str(payload.get("source_job_id"))
    if source_job_id not in ALLOWED_SOURCE_JOB_IDS:
        raise ReportValidationError(f"source_job_id 僅允許 {sorted(ALLOWED_SOURCE_JOB_IDS)}")
    if expected_source_job_id is not None and source_job_id != expected_source_job_id:
        raise ReportValidationError(
            f"contract 違反: 此槽位應為 #{expected_source_job_id} 來源，"
            f"但 payload 宣告為 #{source_job_id}"
        )

    # --- contract: 時間格式 ---
    try:
        data_date = date.fromisoformat(str(payload.get("data_date")))
    except Exception as exc:
        raise ReportValidationError("data_date 必須是 YYYY-MM-DD") from exc

    try:
        generated_at = datetime.fromisoformat(str(payload.get("generated_at")))
    except Exception as exc:
        raise ReportValidationError("generated_at 必須是 ISO-8601 datetime") from exc

    # --- schema: 列欄位型別與唯一性 ---
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ReportValidationError("rows 必須是非空 list")

    seen_stock_ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ReportValidationError(f"rows[{index}] 必須是 object")
        missing = [field for field in REQUIRED_ROW_FIELDS if field not in row]
        if missing:
            raise ReportValidationError(f"rows[{index}] 缺少欄位: {', '.join(missing)}")

        stock_id = row.get("stock_id")
        if not isinstance(stock_id, str) or not stock_id.strip():
            raise ReportValidationError(f"rows[{index}] stock_id 必須是非空字串")
        if stock_id in seen_stock_ids:
            raise ReportValidationError(f"rows[{index}] stock_id 重複: {stock_id}")
        seen_stock_ids.add(stock_id)

        for field in NUMERIC_ROW_FIELDS:
            if not _is_real_number(row.get(field)):
                raise ReportValidationError(
                    f"rows[{index}] 欄位 {field} 必須是數字（不可為 bool/字串/null）"
                )

    # --- health: 狀態閘門 ---
    health = payload.get("health")
    if not isinstance(health, dict):
        raise ReportValidationError("health 必須是 object")
    health_status = str(health.get("status", "")).lower()
    if health_status not in ALLOWED_HEALTH_STATUSES:
        raise ReportValidationError(
            f"health.status 僅允許 {sorted(ALLOWED_HEALTH_STATUSES)}，得到 {health.get('status')!r}"
        )
    if health_status in BLOCKING_HEALTH_STATUSES:
        raise ReportValidationError(f"health 不可交付: status={health_status}")

    # --- freshness: 當日且非未來 ---
    check_now = now or datetime.now()
    target_date = (
        date.fromisoformat(expected_data_date)
        if isinstance(expected_data_date, str)
        else (expected_data_date or check_now.date())
    )
    if data_date != target_date:
        raise ReportValidationError(
            f"freshness 驗證失敗: data_date={data_date.isoformat()} 不是預期 {target_date.isoformat()}"
        )
    if generated_at.date() != target_date:
        raise ReportValidationError(
            f"generated_at 日期不符: {generated_at.date().isoformat()} 不是預期 {target_date.isoformat()}"
        )
    if generated_at > check_now + future_skew:
        raise ReportValidationError(
            f"freshness 驗證失敗: generated_at={generated_at.isoformat()} 是未來時間"
            f"（now={check_now.isoformat()}）"
        )

    return ValidationResult(
        source_job_id=source_job_id,
        data_date=data_date.isoformat(),
        row_count=len(rows),
        generated_at=generated_at.replace(microsecond=0).isoformat(),
        health_status=health_status,
    )


def current_schedule_stage(now: datetime) -> str:
    current = now.time()
    if current < time(17, 30):
        return "before_106_produce"
    if current < time(17, 45):
        return "prefer_106_produce"
    if current < VALIDATION_WINDOW_START:
        return "fetch_201_fallback_ready"
    if current <= VALIDATION_WINDOW_END:
        return "validation_window"
    if current < DELIVERY_DEADLINE:
        return "prepare_delivery"
    return "delivery_deadline"


def deliver_prefer_106_fallback_201(
    *,
    preferred_106_path: str | Path,
    fallback_201_path: str | Path,
    output_dir: str | Path,
    now: datetime | None = None,
    expected_data_date: date | str | None = None,
) -> DeliveryDecision:
    check_now = now or datetime.now()
    preferred_106_path = _coerce_path(preferred_106_path)
    fallback_201_path = _coerce_path(fallback_201_path)
    output_dir = _coerce_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = (
        ("106", "preferred", preferred_106_path),
        ("201", "fallback", fallback_201_path),
    )

    errors: dict[str, str] = {}
    audit: list[dict[str, Any]] = []
    selected_path: Path | None = None
    selected_result: ValidationResult | None = None

    for expected_id, role, candidate_path in candidates:
        if selected_path is not None:
            # 前一個來源已雀屏中選，後續來源不需評估，記錄為 skipped 以保留稽核軌跡。
            audit.append(
                {"source_job_id": expected_id, "role": role, "path": str(candidate_path), "status": "skipped"}
            )
            continue
        try:
            result = validate_payload(
                load_payload(candidate_path),
                now=check_now,
                expected_source_job_id=expected_id,
                expected_data_date=expected_data_date,
            )
            selected_path = candidate_path
            selected_result = result
            audit.append(
                {
                    "source_job_id": expected_id,
                    "role": role,
                    "path": str(candidate_path),
                    "status": "selected",
                    "health_status": result.health_status,
                }
            )
        except Exception as exc:
            errors[expected_id] = str(exc)
            audit.append(
                {
                    "source_job_id": expected_id,
                    "role": role,
                    "path": str(candidate_path),
                    "status": "rejected",
                    "error": str(exc),
                }
            )

    if selected_path is None or selected_result is None:
        raise ReportValidationError(
            "106/201 皆不可交付：" + "; ".join(f"#{name}={msg}" for name, msg in errors.items())
        )

    delivery_payload_path = output_dir / "institutional_daily_report.json"
    manifest_path = output_dir / "delivery_manifest.json"
    shutil.copyfile(selected_path, delivery_payload_path)

    delivered_within_deadline = check_now.time() <= DELIVERY_DEADLINE
    fallback_triggered = selected_result.source_job_id == "201"

    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "schedule": SCHEDULE,
        "delivered_at": check_now.replace(microsecond=0).isoformat(),
        "stage": current_schedule_stage(check_now),
        "delivered_within_deadline": delivered_within_deadline,
        "selected_source_job_id": selected_result.source_job_id,
        "selected_payload_path": str(selected_path),
        "fallback_triggered": fallback_triggered,
        "selected_data_date": selected_result.data_date,
        "row_count": selected_result.row_count,
        "health_status": selected_result.health_status,
        "delivery_payload_path": str(delivery_payload_path),
        "delivery_payload_sha256": _sha256_file(delivery_payload_path),
        "candidates": audit,
        "validation_errors": errors,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return DeliveryDecision(
        selected_source_job_id=selected_result.source_job_id,
        selected_payload_path=str(selected_path),
        selected_data_date=selected_result.data_date,
        fallback_triggered=fallback_triggered,
        delivery_payload_path=str(delivery_payload_path),
        manifest_path=str(manifest_path),
        health_status=selected_result.health_status,
        delivered_within_deadline=delivered_within_deadline,
    )
