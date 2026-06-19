import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from depts.delivery_dept.institutional_daily_report import (
    ReportValidationError,
    build_preferred_106_payload,
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


if __name__ == "__main__":
    unittest.main()
