import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from depts.delivery_dept.institutional_daily_report import (
    DELIVERY_DEADLINE,
    ReportValidationError,
    build_preferred_106_payload,
    current_schedule_stage,
    deliver_prefer_106_fallback_201,
    validate_payload,
    write_payload,
)


class InstitutionalDailyReportBlueprintTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 6, 19, 18, 5, 0)
        self.rows = [
            {
                "stock_id": "2330",
                "foreign": 123456,
                "trust": 2345,
                "dealer": -456,
                "total_balance": 125345,
            }
        ]

    def test_happy_path_prefers_106(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferred = root / "106.json"
            fallback = root / "201.json"
            output = root / "delivery"
            write_payload(
                preferred,
                build_preferred_106_payload(data_date="2026-06-19", rows=self.rows, generated_at=self.now),
            )
            fallback_payload = build_preferred_106_payload(
                data_date="2026-06-19", rows=self.rows, generated_at=self.now
            )
            fallback_payload["source_job_id"] = "201"
            write_payload(fallback, fallback_payload)

            decision = deliver_prefer_106_fallback_201(
                preferred_106_path=preferred,
                fallback_201_path=fallback,
                output_dir=output,
                now=self.now,
            )

            self.assertEqual(decision.selected_source_job_id, "106")
            self.assertFalse(decision.fallback_triggered)
            manifest = json.loads((output / "delivery_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["selected_source_job_id"], "106")
            self.assertEqual(manifest["schedule"]["delivery_deadline"], "18:30")

    def test_stale_data_date_falls_back_to_201(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferred = root / "106.json"
            fallback = root / "201.json"
            output = root / "delivery"
            stale_payload = build_preferred_106_payload(
                data_date="2026-06-18", rows=self.rows, generated_at=self.now
            )
            write_payload(preferred, stale_payload)
            fallback_payload = build_preferred_106_payload(
                data_date="2026-06-19", rows=self.rows, generated_at=self.now
            )
            fallback_payload["source_job_id"] = "201"
            write_payload(fallback, fallback_payload)

            decision = deliver_prefer_106_fallback_201(
                preferred_106_path=preferred,
                fallback_201_path=fallback,
                output_dir=output,
                now=self.now,
            )

            self.assertEqual(decision.selected_source_job_id, "201")
            self.assertTrue(decision.fallback_triggered)
            manifest = json.loads((output / "delivery_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("freshness 驗證失敗", manifest["validation_errors"]["106"])

    def test_missing_required_field_is_rejected(self):
        payload = build_preferred_106_payload(
            data_date="2026-06-19",
            rows=[{"stock_id": "2330", "foreign": 1, "trust": 2, "dealer": 3}],
            generated_at=self.now,
        )
        with self.assertRaises(ReportValidationError) as ctx:
            validate_payload(payload, now=self.now)
        self.assertIn("total_balance", str(ctx.exception))

    def test_bad_format_is_rejected(self):
        payload = build_preferred_106_payload(
            data_date="2026-06-19", rows=self.rows, generated_at=self.now
        )
        payload["generated_at"] = "2026/06/19 18:05:00"
        with self.assertRaises(ReportValidationError) as ctx:
            validate_payload(payload, now=self.now)
        self.assertIn("generated_at 必須是 ISO-8601 datetime", str(ctx.exception))

    # --- 強化後的嚴謹度測試 ---

    def _payload(self, **overrides):
        payload = build_preferred_106_payload(
            data_date="2026-06-19", rows=self.rows, generated_at=self.now
        )
        payload.update(overrides)
        return payload

    def test_contract_slot_mismatch_is_rejected(self):
        # #106 槽位塞了一份宣告自己是 #201 的成品 → 應因 contract 違反被拒。
        payload = self._payload(source_job_id="201")
        with self.assertRaises(ReportValidationError) as ctx:
            validate_payload(payload, now=self.now, expected_source_job_id="106")
        self.assertIn("contract 違反", str(ctx.exception))

    def test_red_health_is_rejected(self):
        payload = self._payload(health={"status": "red", "checks": ["schema"]})
        with self.assertRaises(ReportValidationError) as ctx:
            validate_payload(payload, now=self.now)
        self.assertIn("health 不可交付", str(ctx.exception))

    def test_unknown_health_status_is_rejected(self):
        payload = self._payload(health={"status": "unknown"})
        with self.assertRaises(ReportValidationError) as ctx:
            validate_payload(payload, now=self.now)
        self.assertIn("health.status 僅允許", str(ctx.exception))

    def test_yellow_health_is_accepted(self):
        payload = self._payload(health={"status": "yellow", "checks": ["degraded"]})
        result = validate_payload(payload, now=self.now)
        self.assertEqual(result.health_status, "yellow")

    def test_duplicate_stock_id_is_rejected(self):
        rows = [dict(self.rows[0]), dict(self.rows[0])]
        payload = self._payload(rows=rows)
        with self.assertRaises(ReportValidationError) as ctx:
            validate_payload(payload, now=self.now)
        self.assertIn("stock_id 重複", str(ctx.exception))

    def test_non_numeric_field_is_rejected(self):
        bad_row = dict(self.rows[0])
        bad_row["foreign"] = "123456"  # 字串而非數字
        payload = self._payload(rows=[bad_row])
        with self.assertRaises(ReportValidationError) as ctx:
            validate_payload(payload, now=self.now)
        self.assertIn("foreign", str(ctx.exception))

    def test_bool_disguised_as_number_is_rejected(self):
        bad_row = dict(self.rows[0])
        bad_row["dealer"] = True  # bool 是 int 子類，但不該通過
        payload = self._payload(rows=[bad_row])
        with self.assertRaises(ReportValidationError) as ctx:
            validate_payload(payload, now=self.now)
        self.assertIn("dealer", str(ctx.exception))

    def test_empty_stock_id_is_rejected(self):
        bad_row = dict(self.rows[0])
        bad_row["stock_id"] = "  "
        payload = self._payload(rows=[bad_row])
        with self.assertRaises(ReportValidationError) as ctx:
            validate_payload(payload, now=self.now)
        self.assertIn("stock_id 必須是非空字串", str(ctx.exception))

    def test_future_generated_at_is_rejected(self):
        future = self.now + timedelta(hours=2)
        payload = build_preferred_106_payload(
            data_date="2026-06-19", rows=self.rows, generated_at=future
        )
        with self.assertRaises(ReportValidationError) as ctx:
            validate_payload(payload, now=self.now)
        self.assertIn("是未來時間", str(ctx.exception))

    def test_missing_health_field_is_rejected(self):
        payload = self._payload()
        del payload["health"]
        with self.assertRaises(ReportValidationError) as ctx:
            validate_payload(payload, now=self.now)
        self.assertIn("health", str(ctx.exception))

    def test_expected_data_date_overrides_today(self):
        # 例如假日後第一個交易日，data_date 可能不是 now.date()，可由呼叫端指定。
        payload = build_preferred_106_payload(
            data_date="2026-06-18",
            rows=self.rows,
            generated_at=datetime(2026, 6, 18, 18, 5, 0),
        )
        result = validate_payload(payload, now=self.now, expected_data_date="2026-06-18")
        self.assertEqual(result.data_date, "2026-06-18")

    def test_red_health_106_falls_back_to_201(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferred = root / "106.json"
            fallback = root / "201.json"
            output = root / "delivery"
            sick = build_preferred_106_payload(
                data_date="2026-06-19",
                rows=self.rows,
                generated_at=self.now,
                health={"status": "red", "checks": ["schema"]},
            )
            write_payload(preferred, sick)
            fallback_payload = build_preferred_106_payload(
                data_date="2026-06-19", rows=self.rows, generated_at=self.now
            )
            fallback_payload["source_job_id"] = "201"
            write_payload(fallback, fallback_payload)

            decision = deliver_prefer_106_fallback_201(
                preferred_106_path=preferred,
                fallback_201_path=fallback,
                output_dir=output,
                now=self.now,
            )

            self.assertEqual(decision.selected_source_job_id, "201")
            self.assertTrue(decision.fallback_triggered)
            manifest = json.loads((output / "delivery_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("health 不可交付", manifest["validation_errors"]["106"])

    def test_manifest_is_enriched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferred = root / "106.json"
            fallback = root / "201.json"
            output = root / "delivery"
            write_payload(
                preferred,
                build_preferred_106_payload(
                    data_date="2026-06-19", rows=self.rows, generated_at=self.now
                ),
            )
            fb = build_preferred_106_payload(
                data_date="2026-06-19", rows=self.rows, generated_at=self.now
            )
            fb["source_job_id"] = "201"
            write_payload(fallback, fb)

            decision = deliver_prefer_106_fallback_201(
                preferred_106_path=preferred,
                fallback_201_path=fallback,
                output_dir=output,
                now=self.now,
            )

            manifest = json.loads((output / "delivery_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["manifest_schema_version"], "1.0")
            self.assertTrue(manifest["delivered_within_deadline"])
            self.assertEqual(manifest["health_status"], "green")
            self.assertEqual(len(manifest["delivery_payload_sha256"]), 64)
            statuses = {c["source_job_id"]: c["status"] for c in manifest["candidates"]}
            self.assertEqual(statuses["106"], "selected")
            self.assertEqual(statuses["201"], "skipped")
            self.assertTrue(decision.delivered_within_deadline)

    def test_slot_mismatch_in_delivery_is_rejected_and_falls_back(self):
        # 106 槽位放了宣告 source_job_id=201 的成品 → 106 應被 contract 拒，改用真正的 201。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferred = root / "106.json"
            fallback = root / "201.json"
            output = root / "delivery"
            wrong = build_preferred_106_payload(
                data_date="2026-06-19", rows=self.rows, generated_at=self.now
            )
            wrong["source_job_id"] = "201"
            write_payload(preferred, wrong)
            real_201 = build_preferred_106_payload(
                data_date="2026-06-19", rows=self.rows, generated_at=self.now
            )
            real_201["source_job_id"] = "201"
            write_payload(fallback, real_201)

            decision = deliver_prefer_106_fallback_201(
                preferred_106_path=preferred,
                fallback_201_path=fallback,
                output_dir=output,
                now=self.now,
            )

            self.assertEqual(decision.selected_source_job_id, "201")
            manifest = json.loads((output / "delivery_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("contract 違反", manifest["validation_errors"]["106"])

    def test_both_invalid_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferred = root / "106.json"
            fallback = root / "201.json"
            output = root / "delivery"
            stale = build_preferred_106_payload(
                data_date="2026-06-01", rows=self.rows, generated_at=self.now
            )
            write_payload(preferred, stale)
            fb = build_preferred_106_payload(
                data_date="2026-06-01", rows=self.rows, generated_at=self.now
            )
            fb["source_job_id"] = "201"
            write_payload(fallback, fb)

            with self.assertRaises(ReportValidationError) as ctx:
                deliver_prefer_106_fallback_201(
                    preferred_106_path=preferred,
                    fallback_201_path=fallback,
                    output_dir=output,
                    now=self.now,
                )
            self.assertIn("皆不可交付", str(ctx.exception))

    def test_schedule_stage_boundaries(self):
        self.assertEqual(current_schedule_stage(datetime(2026, 6, 19, 17, 0)), "before_106_produce")
        self.assertEqual(current_schedule_stage(datetime(2026, 6, 19, 17, 30)), "prefer_106_produce")
        self.assertEqual(current_schedule_stage(datetime(2026, 6, 19, 17, 45)), "fetch_201_fallback_ready")
        self.assertEqual(current_schedule_stage(datetime(2026, 6, 19, 18, 5)), "validation_window")
        self.assertEqual(current_schedule_stage(datetime(2026, 6, 19, 18, 20)), "prepare_delivery")
        self.assertEqual(current_schedule_stage(datetime(2026, 6, 19, 18, 30)), "delivery_deadline")

    def test_late_delivery_flag(self):
        late = datetime(2026, 6, 19, 18, 45, 0)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferred = root / "106.json"
            fallback = root / "201.json"
            output = root / "delivery"
            write_payload(
                preferred,
                build_preferred_106_payload(
                    data_date="2026-06-19", rows=self.rows, generated_at=self.now
                ),
            )
            fb = build_preferred_106_payload(
                data_date="2026-06-19", rows=self.rows, generated_at=self.now
            )
            fb["source_job_id"] = "201"
            write_payload(fallback, fb)

            decision = deliver_prefer_106_fallback_201(
                preferred_106_path=preferred,
                fallback_201_path=fallback,
                output_dir=output,
                now=late,
            )
            self.assertFalse(decision.delivered_within_deadline)
            self.assertGreater(late.time(), DELIVERY_DEADLINE)


if __name__ == "__main__":
    unittest.main()
