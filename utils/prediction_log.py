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


def log_closed(ticker, name, action, confidence, strategy, entry_price, actual_price,
               ts=None, horizon_days=DEFAULT_HORIZON_DAYS, source="seed"):
    """直接寫入一筆「已結算」預測（用歷史資料補考用）。

    entry_price=當時價、actual_price=horizon 後的真實價。中性(HOLD)不計分回 False。
    為避免重複灌入，相同 (ticker, ts, source) 視為已存在則跳過。
    """
    init_db()
    direction = _direction(action)
    if direction not in ("long", "short") or not entry_price or not actual_price:
        return False
    ret = (actual_price - entry_price) / entry_price * 100.0
    correct = 1 if ((direction == "long" and ret > 0) or (direction == "short" and ret < 0)) else 0
    ts = ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _conn() as con:
            dup = con.execute(
                "SELECT 1 FROM predictions WHERE ticker=? AND ts=? AND status='closed'",
                (ticker, ts)).fetchone()
            if dup:
                return False
            con.execute(
                """INSERT INTO predictions
                   (ts,ticker,name,action,direction,confidence,strategy,entry_price,
                    horizon_days,due_date,actual_price,actual_return,correct,status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'closed')""",
                (ts, ticker, name, action, direction, confidence, strategy,
                 float(entry_price), horizon_days, ts[:10],
                 round(float(actual_price), 2), round(ret, 2), correct),
            )
        return True
    except Exception as e:
        print(f"❌ log_closed 失敗: {e}")
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
    """買進選股訊號 vs 減碼/出場(風控)分開的歷史命中率，供 !accuracy 顯示。

    2026-07-05 修正(harness 審計):原本把 REDUCE/減碼、EXIT/出場 當「看空賭注」與 BUY 混算成
    單一命中率(壓成 ~46% 假象、埋掉買進訊號真實 ~61% 的方向命中);平均報酬又用 raw return
    (沒調方向)顯示成假正值。現改為兩塊:買進訊號(選股 edge)為頭條;減碼/出場另計「事後是否
    真的下跌」當風控參考,不混算。by_strategy 維持「全部」語意不變,strategy_weights 的 Kelly
    倉位不受影響;by_strategy_buy 才是顯示用(只買進)。
    """
    init_db()
    with _conn() as con:
        total_open = con.execute(
            "SELECT COUNT(*) FROM predictions WHERE status='open'").fetchone()[0]
        closed = con.execute(
            "SELECT direction, correct, strategy, actual_return "
            "FROM predictions WHERE status='closed'"
        ).fetchall()

    n = len(closed)
    if n == 0:
        return {"closed": 0, "open": total_open, "hit_rate": None, "avg_return": None,
                "by_strategy": [], "by_strategy_buy": [],
                "buy_n": 0, "buy_hit_rate": None, "buy_avg_return": None,
                "riskoff_n": 0, "riskoff_drop_rate": None, "riskoff_avg_return": None}

    longs = [r for r in closed if r["direction"] == "long" and r["correct"] is not None]
    riskoff = [r for r in closed if r["direction"] == "short" and r["correct"] is not None]

    def _bucket(rs):
        m = len(rs)
        if m == 0:
            return 0, None, None
        hit = round(sum(r["correct"] for r in rs) / m * 100, 1)
        avg = round(sum((r["actual_return"] or 0.0) for r in rs) / m, 2)
        return m, hit, avg

    buy_n, buy_hit, buy_avg = _bucket(longs)     # correct==1 → 看多後漲
    ro_n, ro_drop, ro_avg = _bucket(riskoff)     # correct==1 → 減碼/出場後真的跌(風控對)

    def _by(rows):
        d = {}
        for r in rows:
            if r["correct"] is None:
                continue
            s = r["strategy"] or "未知"
            d.setdefault(s, [0, 0]); d[s][1] += 1; d[s][0] += r["correct"]
        return sorted(
            [{"strategy": s, "hits": h, "n": c, "rate": round(h / c * 100, 1)}
             for s, (h, c) in d.items()],
            key=lambda x: x["n"], reverse=True)

    return {
        "closed": n, "open": total_open,
        # 頭條 = 買進選股訊號(誠實 edge);相容舊 hit_rate/avg_return 也指這個
        "buy_n": buy_n, "buy_hit_rate": buy_hit, "buy_avg_return": buy_avg,
        "hit_rate": buy_hit, "avg_return": buy_avg,
        "by_strategy": _by(closed),          # 全部(給 Kelly / strategy_weights,語意不變)
        "by_strategy_buy": _by(longs),       # 只買進(給 !accuracy 顯示,與頭條一致)
        "riskoff_n": ro_n, "riskoff_drop_rate": ro_drop, "riskoff_avg_return": ro_avg,
    }
