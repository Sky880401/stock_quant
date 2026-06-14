"""
P2 多源資料：新聞情緒（零 API 成本，關鍵字詞典）+ 融資融券趨勢（FinMind）。

成本紀律（北極星目標）：新聞情緒不呼叫 LLM，用中文財經詞典即時計分，
避免每次查股都燒 token；要更準再考慮升級。
"""
from datetime import datetime, timedelta

from crawlers.news_scraper import fetch_yahoo_news


# 單例 FinMind DataLoader：原本 margin_trend 每次都新建 DataLoader 並重新 login_by_token，
# 累積連線池造成洩漏。改為全程重用、只登入一次。
_DL = None


def _get_loader():
    global _DL
    if _DL is None:
        import os as _os
        from FinMind.data import DataLoader
        _DL = DataLoader()
        tok = _os.getenv("FINMIND_TOKEN")
        if tok:
            try:
                _DL.login_by_token(api_token=tok)
            except Exception:
                pass
    return _DL

# 中文財經情緒詞典（標題層級夠用；命中即計數）
_POS = ["漲", "大漲", "飆", "創新高", "新高", "看好", "買超", "利多", "樂觀", "成長",
        "獲利", "突破", "強勢", "上調", "調高", "訂單", "旺", "受惠", "回升", "反彈",
        "增持", "加碼", "佳", "優於預期", "題材", "點火"]
_NEG = ["跌", "大跌", "重挫", "跌停", "看壞", "賣超", "利空", "悲觀", "衰退", "虧損",
        "跌破", "弱勢", "下調", "調降", "警訊", "賣壓", "疑慮", "下滑", "風險", "摜壓",
        "減持", "出脫", "示警", "不如預期", "套牢", "認賠"]


def news_sentiment(stock_id: str) -> dict:
    """抓 Yahoo 個股新聞標題並做詞典情緒計分。score 介於 -1~1。"""
    clean = str(stock_id).split(".")[0]
    try:
        headlines = fetch_yahoo_news(clean)
    except Exception:
        headlines = []
    if not headlines:
        return {"score": 0.0, "label": "無新聞", "pos": 0, "neg": 0, "headlines": []}

    pos = neg = 0
    for h in headlines:
        pos += sum(1 for w in _POS if w in h)
        neg += sum(1 for w in _NEG if w in h)

    total = pos + neg
    score = round((pos - neg) / total, 2) if total else 0.0
    if score > 0.2:
        label = "偏多"
    elif score < -0.2:
        label = "偏空"
    else:
        label = "中性"
    return {"score": score, "label": label, "pos": pos, "neg": neg,
            "headlines": headlines[:5]}


def margin_trend(stock_id: str, days: int = 20) -> dict:
    """融資融券趨勢：融資增＝散戶追價(過熱偏空)、融券增＝空方壓力/軋空潛力。

    用 FinMind taiwan_stock_margin_purchase_short_sale。抓不到回中性。
    """
    clean = str(stock_id).split(".")[0]
    if not clean.isdigit():
        return {"status": "N/A", "reason": "非台股代號", "score": 0}
    try:
        dl = _get_loader()
        start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")
        df = dl.taiwan_stock_margin_purchase_short_sale(
            stock_id=clean, start_date=start, end_date=end)
        if df is None or df.empty or len(df) < 2:
            return {"status": "N/A", "reason": "無融資券資料", "score": 0}
        df = df.sort_values("date")
        # 當日變化 = 最新一日餘額 - 前一日餘額（單位：張）。MarginPurchase=融資, ShortSale=融券
        mlast, mprev = df["MarginPurchaseTodayBalance"].iloc[-1], df["MarginPurchaseTodayBalance"].iloc[-2]
        slast, sprev = df["ShortSaleTodayBalance"].iloc[-1], df["ShortSaleTodayBalance"].iloc[-2]
        margin_chg = int(mlast - mprev)
        short_chg = int(slast - sprev)
        dstr = str(df["date"].iloc[-1])[5:]
        reasons, score = [f"{dstr}當日:"], 0
        if margin_chg > 0:
            reasons.append(f"融資增{margin_chg}張(散戶追價)"); score -= 0.5
        elif margin_chg < 0:
            reasons.append(f"融資減{abs(margin_chg)}張(籌碼沉澱)"); score += 0.5
        else:
            reasons.append("融資持平")
        if short_chg > 0:
            reasons.append(f"融券增{short_chg}張(空方/軋空潛力)")
        elif short_chg < 0:
            reasons.append(f"融券減{abs(short_chg)}張")
        # 借券賣出餘額淨增（SBL，外資/法人放空管道，比融券更能反映法人空方）
        sbl_chg = 0
        try:
            sb = dl.taiwan_daily_short_sale_balances(stock_id=clean, start_date=start, end_date=end)
            if sb is not None and not sb.empty:
                sr = sb.sort_values("date").iloc[-1]
                sbl_chg = int((sr["SBLShortSalesCurrentDayBalance"] - sr["SBLShortSalesPreviousDayBalance"]) / 1000)
                if sbl_chg > 0:
                    reasons.append(f"借券賣出餘額增{sbl_chg}張(法人空方增)"); score -= 0.3
                elif sbl_chg < 0:
                    reasons.append(f"借券賣出餘額減{abs(sbl_chg)}張(空方回補)"); score += 0.3
        except Exception:
            pass
        status = "偏空(資增)" if score < 0 else ("偏多(資減)" if score > 0 else "中性")
        return {"status": status, "reason": " | ".join(reasons), "score": score,
                "margin_change": margin_chg, "short_change": short_chg, "sbl_change": sbl_chg}
    except Exception as e:
        return {"status": "N/A", "reason": f"融資券抓取失敗:{str(e)[:40]}", "score": 0}
