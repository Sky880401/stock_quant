from __future__ import annotations

"""法人日報藍圖骨架：prefer #106 / fallback #201。

本模組只提供可測試的最小閉環，不直接部署 #106。用途：
1. #106 producer 產出 JSON 成品（可由別處呼叫 build_preferred_106_payload）。
2. 18:00-18:10 驗證 contract/schema/health/freshness。
3. 驗證失敗時，自動 fallback 到 #201。
4. 18:30 前一定挑出一份可交付成品並寫出 delivery manifest。
"""

from dataclasses import dataclass
from datetime import date, datetime, time
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

REQUIRED_META_FIELDS = (
    "schema_version",
    "report_type",
    "source_job_id",
    "data_date",
    "generated_at",
    "rows",
)
REQUIRED_ROW_FIELDS = ("stock_id", "foreign", "trust", "dealer", "total_balance")
ALLOWED_SOURCE_JOB_IDS = {"106", "201"}
REPORT_TYPE = "institutional_daily_report"
SCHEMA_VERSION = "1.0"


class ReportValidationError(ValueError):
    """法人日報 contract/schema/health/freshness 驗證失敗。"""


@dataclass(frozen=True)
class ValidationResult:
    source_job_id: str
    data_date: str
    row_count: int
    generated_at: str


@dataclass(frozen=True)
class DeliveryDecision:
    selected_source_job_id: str
    selected_payload_path: str
    selected_data_date: str
    fallback_triggered: bool
    delivery_payload_path: str
    manifest_path: str


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


def validate_payload(payload: dict[str, Any], *, now: datetime | None = None) -> ValidationResult:
    if not isinstance(payload, dict):
        raise ReportValidationError("payload 必須是 object")

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

    try:
        data_date = date.fromisoformat(str(payload.get("data_date")))
    except Exception as exc:
        raise ReportValidationError("data_date 必須是 YYYY-MM-DD") from exc

    try:
        generated_at = datetime.fromisoformat(str(payload.get("generated_at")))
    except Exception as exc:
        raise ReportValidationError("generated_at 必須是 ISO-8601 datetime") from exc

    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ReportValidationError("rows 必須是非空 list")

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ReportValidationError(f"rows[{index}] 必須是 object")
        missing = [field for field in REQUIRED_ROW_FIELDS if field not in row]
        if missing:
            raise ReportValidationError(f"rows[{index}] 缺少欄位: {', '.join(missing)}")

    health = payload.get("health")
    if health is not None and not isinstance(health, dict):
        raise ReportValidationError("health 必須是 object")

    check_now = now or datetime.now()
    if data_date != check_now.date():
        raise ReportValidationError(
            f"freshness 驗證失敗: data_date={data_date.isoformat()} 不是今日 {check_now.date().isoformat()}"
        )
    if generated_at.date() != check_now.date():
        raise ReportValidationError(
            f"generated_at 日期不符: {generated_at.date().isoformat()} 不是今日 {check_now.date().isoformat()}"
        )

    return ValidationResult(
        source_job_id=source_job_id,
        data_date=data_date.isoformat(),
        row_count=len(rows),
        generated_at=generated_at.replace(microsecond=0).isoformat(),
    )


def current_schedule_stage(now: datetime) -> str:
    current = now.time()
    if current < time(17, 30):
        return "before_106_produce"
    if current < time(17, 45):
        return "prefer_106_produce"
    if current < time(18, 0):
        return "fetch_201_fallback_ready"
    if current <= time(18, 10):
        return "validation_window"
    if current < time(18, 30):
        return "prepare_delivery"
    return "delivery_deadline"


def deliver_prefer_106_fallback_201(
    *,
    preferred_106_path: str | Path,
    fallback_201_path: str | Path,
    output_dir: str | Path,
    now: datetime | None = None,
) -> DeliveryDecision:
    check_now = now or datetime.now()
    preferred_106_path = _coerce_path(preferred_106_path)
    fallback_201_path = _coerce_path(fallback_201_path)
    output_dir = _coerce_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    errors: dict[str, str] = {}
    selected_path: Path | None = None
    selected_result: ValidationResult | None = None

    for source_name, candidate_path in (("106", preferred_106_path), ("201", fallback_201_path)):
        try:
            result = validate_payload(load_payload(candidate_path), now=check_now)
            selected_path = candidate_path
            selected_result = result
            break
        except Exception as exc:
            errors[source_name] = str(exc)

    if selected_path is None or selected_result is None:
        raise ReportValidationError(
            "106/201 皆不可交付：" + "; ".join(f"#{name}={msg}" for name, msg in errors.items())
        )

    delivery_payload_path = output_dir / "institutional_daily_report.json"
    manifest_path = output_dir / "delivery_manifest.json"
    shutil.copyfile(selected_path, delivery_payload_path)
    manifest = {
        "schedule": SCHEDULE,
        "delivered_at": check_now.replace(microsecond=0).isoformat(),
        "stage": current_schedule_stage(check_now),
        "selected_source_job_id": selected_result.source_job_id,
        "selected_payload_path": str(selected_path),
        "fallback_triggered": selected_result.source_job_id == "201",
        "selected_data_date": selected_result.data_date,
        "row_count": selected_result.row_count,
        "validation_errors": errors,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return DeliveryDecision(
        selected_source_job_id=selected_result.source_job_id,
        selected_payload_path=str(selected_path),
        selected_data_date=selected_result.data_date,
        fallback_triggered=selected_result.source_job_id == "201",
        delivery_payload_path=str(delivery_payload_path),
        manifest_path=str(manifest_path),
    )
