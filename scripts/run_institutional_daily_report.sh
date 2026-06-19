#!/usr/bin/env bash
#
# 法人日報 prefer #106 / fallback #201 — 交付 wrapper（#901，僅驗證+交付，不部署 #106）。
#
# 排程（與 docs/INSTITUTIONAL_DAILY_REPORT_BLUEPRINT.md 一致）：
#   17:30  #106 producer 產出 <BASE>/<YYYY-MM-DD>/106_preferred.json
#   17:45  #201 relay 抓取 <BASE>/<YYYY-MM-DD>/201_fallback.json
#   18:00  本 wrapper 進入驗證視窗（18:00–18:10）並於失敗時 fallback
#   18:30  必送：本 wrapper 應在此前完成交付
#
# 對應 crontab（正式機才掛；本分支只做開發測試，不掛 cron、不部署）：
#   0 18 * * 1-5  /path/to/scripts/run_institutional_daily_report.sh >> /var/log/idr.log 2>&1
#
# 用法：
#   INSTITUTIONAL_DAILY_BASE_DIR=/data/institutional_daily ./scripts/run_institutional_daily_report.sh
#   ./scripts/run_institutional_daily_report.sh /data/institutional_daily 2026-06-19
#
# 參數：
#   $1  base dir（可選，預設讀環境變數 INSTITUTIONAL_DAILY_BASE_DIR）
#   $2  expected data date YYYY-MM-DD（可選，不給則由現在時刻推導最近工作日）

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_DIR="${1:-${INSTITUTIONAL_DAILY_BASE_DIR:-}}"
DATA_DATE="${2:-}"

if [[ -z "${BASE_DIR}" ]]; then
  echo "用法: $0 <base_dir> [data_date]  或設定 INSTITUTIONAL_DAILY_BASE_DIR" >&2
  exit 64
fi

ARGS=(-m depts.delivery_dept.institutional_daily_report run --base-dir "${BASE_DIR}")
if [[ -n "${DATA_DATE}" ]]; then
  ARGS+=(--expected-data-date "${DATA_DATE}")
fi

cd "${REPO_ROOT}"
exec python3 "${ARGS[@]}"
