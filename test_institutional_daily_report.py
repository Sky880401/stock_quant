import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from depts.delivery_dept.institutional_daily_report import (
    DELIVERY_DEADLINE,
    DELIVERY_FILENAME,
    FALLBACK_201_FILENAME,
    MANIFEST_FILENAME,
    PREFERRED_106_FILENAME,
    ReportValidationError,
    build_delivery_paths,
    build_fallback_201_payload,
    build_preferred_106_payload,
    current_schedule_stage,
    deliver_prefer_106_fallback_201,
    main,
    resolve_expected_trading_date,
    run_scheduled_delivery,
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


class IntegrationLayerTests(unittest.TestCase):
    """整合層：路徑約定 + 交易日參數流 + cron 入口 + CLI。"""

    def setUp(self):
        self.now = datetime(2026, 6, 19, 18, 5, 0)  # 2026-06-19 是週五
        self.rows = [
            {"stock_id": "2330", "foreign": 123456, "trust": 2345, "dealer": -456, "total_balance": 125345},
        ]

    def _seed_slots(self, base, data_date="2026-06-19", generated_at=None, with_106=True, with_201=True):
        # generated_at 預設與 data_date 同日 18:05（通過 freshness）。
        if generated_at is None:
            d = datetime.fromisoformat(data_date)
            generated_at = datetime(d.year, d.month, d.day, 18, 5, 0)
        paths = build_delivery_paths(base, data_date)
        paths.data_date_dir.mkdir(parents=True, exist_ok=True)
        if with_106:
            write_payload(
                paths.preferred_106_path,
                build_preferred_106_payload(data_date=data_date, rows=self.rows, generated_at=generated_at),
            )
        if with_201:
            write_payload(
                paths.fallback_201_path,
                build_fallback_201_payload(data_date=data_date, rows=self.rows, generated_at=generated_at),
            )
        return paths

    def test_build_delivery_paths_convention(self):
        paths = build_delivery_paths("/data/idr", "2026-06-19")
        self.assertTrue(str(paths.preferred_106_path).endswith(f"2026-06-19/{PREFERRED_106_FILENAME}"))
        self.assertTrue(str(paths.fallback_201_path).endswith(f"2026-06-19/{FALLBACK_201_FILENAME}"))
        self.assertTrue(str(paths.delivery_payload_path).endswith(f"delivery/{DELIVERY_FILENAME}"))
        self.assertTrue(str(paths.manifest_path).endswith(f"delivery/{MANIFEST_FILENAME}"))

    def test_resolve_expected_trading_date_skips_weekend(self):
        # 週六 → 退到週五；週日 → 退到週五；平日 → 當天。
        self.assertEqual(resolve_expected_trading_date(datetime(2026, 6, 20, 18, 5)), "2026-06-19")
        self.assertEqual(resolve_expected_trading_date(datetime(2026, 6, 21, 18, 5)), "2026-06-19")
        self.assertEqual(resolve_expected_trading_date(datetime(2026, 6, 19, 18, 5)), "2026-06-19")

    def test_fallback_201_builder_marks_yellow(self):
        payload = build_fallback_201_payload(data_date="2026-06-19", rows=self.rows, generated_at=self.now)
        self.assertEqual(payload["source_job_id"], "201")
        self.assertEqual(payload["health"]["status"], "yellow")
        result = validate_payload(payload, now=self.now, expected_source_job_id="201")
        self.assertEqual(result.health_status, "yellow")

    def test_run_scheduled_delivery_prefers_106(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._seed_slots(tmp)
            decision = run_scheduled_delivery(base_dir=tmp, now=self.now)
            self.assertEqual(decision.selected_source_job_id, "106")
            self.assertFalse(decision.fallback_triggered)
            self.assertTrue(Path(decision.delivery_payload_path).exists())
            self.assertTrue(Path(decision.manifest_path).exists())

    def test_run_scheduled_delivery_falls_back_when_106_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._seed_slots(tmp, with_106=False)
            decision = run_scheduled_delivery(base_dir=tmp, now=self.now)
            self.assertEqual(decision.selected_source_job_id, "201")
            self.assertTrue(decision.fallback_triggered)
            self.assertEqual(decision.health_status, "yellow")

    def test_run_scheduled_delivery_uses_expected_data_date(self):
        # 指定交易日 → 讀對應資料夾，即使與 now.date() 不同。
        with tempfile.TemporaryDirectory() as tmp:
            self._seed_slots(tmp, data_date="2026-06-18")
            saturday = datetime(2026, 6, 20, 18, 5, 0)
            decision = run_scheduled_delivery(
                base_dir=tmp, now=saturday, expected_data_date="2026-06-18"
            )
            self.assertEqual(decision.selected_data_date, "2026-06-18")

    def test_run_scheduled_delivery_both_missing_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ReportValidationError) as ctx:
                run_scheduled_delivery(base_dir=tmp, now=self.now)
            self.assertIn("找不到任何來源成品", str(ctx.exception))

    def test_cli_deliver_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferred = root / "106.json"
            fallback = root / "201.json"
            output = root / "out"
            write_payload(
                preferred,
                build_preferred_106_payload(data_date="2026-06-19", rows=self.rows, generated_at=self.now),
            )
            write_payload(
                fallback,
                build_fallback_201_payload(data_date="2026-06-19", rows=self.rows, generated_at=self.now),
            )
            code = main([
                "deliver",
                "--preferred-106", str(preferred),
                "--fallback-201", str(fallback),
                "--output-dir", str(output),
                "--now", self.now.isoformat(),
            ])
            self.assertEqual(code, 0)
            self.assertTrue((output / DELIVERY_FILENAME).exists())
            self.assertTrue((output / MANIFEST_FILENAME).exists())

    def test_cli_run_mode_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._seed_slots(tmp)
            code = main([
                "run",
                "--base-dir", tmp,
                "--expected-data-date", "2026-06-19",
                "--now", self.now.isoformat(),
            ])
            self.assertEqual(code, 0)

    def test_cli_returns_two_when_both_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preferred = root / "106.json"
            fallback = root / "201.json"
            output = root / "out"
            stale = build_preferred_106_payload(data_date="2026-06-01", rows=self.rows, generated_at=self.now)
            write_payload(preferred, stale)
            fb = build_fallback_201_payload(data_date="2026-06-01", rows=self.rows, generated_at=self.now)
            write_payload(fallback, fb)
            code = main([
                "deliver",
                "--preferred-106", str(preferred),
                "--fallback-201", str(fallback),
                "--output-dir", str(output),
                "--now", self.now.isoformat(),
            ])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
