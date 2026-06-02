"""
P1 預測日誌閉環 —— 把每次 BMO 對個股的判斷存下來，等 N 日後回填實際股價，
算出「方向是否命中」，累積成可信的歷史勝率。這是 P4 動態權重的資料地基。

設計原則（誠實面對勝率）：
- 只對「有方向性」的判斷計分（看多/看空）；HOLD/中性不下注 → status=skipped。
- 命中判定：看多→實際報酬>0 算對；看空→實際報酬<0 算對。
- 預測剛存下時 status=open，要等 due_date（約一個月後）才有真實結果可回填。
  系統剛上線那陣子勝率樣本少屬正常，需時間累積。
"""
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "predictions.db"

DEFAULT_HORIZON_DAYS = 30  # 約一個月（~21 個交易日）


def _direction(action: str) -> str:
    a = (action or "").upper()
    if "BUY" in a:
        return "long"
    if "SELL" in a or "EXIT" in a or "REDUCE" in a:
        return "short"
    return "neutral"


def _conn():
    os.makedirs(DB_PATH.parent, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                ticker TEXT NOT NULL,
                name TEXT,
                action TEXT,
                direction TEXT,
                confidence REAL,
                strategy TEXT,
                entry_price REAL,
                horizon_days INTEGER,
                due_date TEXT,
                actual_price REAL,
                actual_return REAL,
                correct INTEGER,
                status TEXT DEFAULT 'open'
            )
            """
        )


def log_prediction(ticker, name, action, confidence, strategy, entry_price,
                   horizon_days=DEFAULT_HORIZON_DAYS):
    """記錄一筆預測。中性(HOLD)判斷標為 skipped、不參與勝率計算。"""
    init_db()
    now = datetime.now()
    direction = _direction(action)
    status = "open" if direction in ("long", "short") else "skipped"
    due = (now + timedelta(days=horizon_days)).strftime("%Y-%m-%d")
    try:
        with _conn() as con:
            con.execute(
                """INSERT INTO predictions
                   (ts,ticker,name,action,direction,confidence,strategy,
                    entry_price,horizon_days,due_date,status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (now.strftime("%Y-%m-%d %H:%M:%S"), ticker, name, action, direction,
                 confidence, strategy, float(entry_price) if entry_price else None,
                 horizon_days, due, status),
            )
        return True
    except Exception as e:
        print(f"❌ 預測日誌寫入失敗: {e}")
        return False


def backfill_matured(price_func):
    """回填已到期(due_date<=今天)且仍 open 的預測。

    price_func(ticker)->float 回傳該股最新收盤價；回 None 表示抓不到、略過。
    回傳 (closed_count, checked_count)。
    """
    init_db()
    today = datetime.now().strftime("%Y-%m-%d")
    closed = checked = 0
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM predictions WHERE status='open' AND due_date<=?", (today,)
        ).fetchall()
        for r in rows:
            checked += 1
            try:
                price = price_func(r["ticker"])
            except Exception:
                price = None
            if not price or not r["entry_price"]:
                continue
            ret = (price - r["entry_price"]) / r["entry_price"] * 100.0
            if r["direction"] == "long":
                correct = 1 if ret > 0 else 0
            elif r["direction"] == "short":
                correct = 1 if ret < 0 else 0
            else:
                continue
            con.execute(
                """UPDATE predictions
                   SET actual_price=?, actual_return=?, correct=?, status='closed'
                   WHERE id=?""",
                (round(price, 2), round(ret, 2), correct, r["id"]),
            )
            closed += 1
    return closed, checked


def accuracy_summary():
    """回傳整體 + 各策略的歷史命中率與樣本數，供 !accuracy 顯示。"""
    init_db()
    with _conn() as con:
        total_open = con.execute(
            "SELECT COUNT(*) FROM predictions WHERE status='open'").fetchone()[0]
        closed = con.execute(
            "SELECT correct, strategy, actual_return FROM predictions WHERE status='closed'"
        ).fetchall()

    n = len(closed)
    if n == 0:
        return {"closed": 0, "open": total_open, "hit_rate": None,
                "avg_return": None, "by_strategy": [], "recent": []}

    hits = sum(r["correct"] for r in closed)
    avg_ret = sum(r["actual_return"] for r in closed) / n

    by = {}
    for r in closed:
        s = r["strategy"] or "未知"
        by.setdefault(s, [0, 0])
        by[s][1] += 1
        by[s][0] += r["correct"]
    by_strategy = sorted(
        [{"strategy": s, "hits": h, "n": cnt, "rate": round(h / cnt * 100, 1)}
         for s, (h, cnt) in by.items()],
        key=lambda x: x["n"], reverse=True,
    )

    return {
        "closed": n,
        "open": total_open,
        "hit_rate": round(hits / n * 100, 1),
        "avg_return": round(avg_ret, 2),
        "by_strategy": by_strategy,
    }
