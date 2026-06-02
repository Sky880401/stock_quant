"""
P3 機率化獲利空間 —— 用「該股自身歷史的 N 日後報酬分佈」回答潛在獲利空間，
取代只給漲跌方向。零 LLM 成本、純統計，誠實面對機率（北極星：要能真評估獲利）。

輸出（持有 horizon 個交易日）：
- prob_up：歷史上 N 日後上漲的機率
- expected_return：期望報酬（均值）
- median_return：中位數報酬
- downside：下檔風險（負報酬樣本的平均）
- p10 / p90：第 10 / 90 百分位（保守 / 樂觀情境）
- target_low / target_high：對應目前股價的價位區間
- samples：樣本數（樣本太少時可信度低，會標註）
"""
import numpy as np

DEFAULT_HORIZON = 20  # 交易日，約一個月


def compute_profit_space(df, horizon: int = DEFAULT_HORIZON) -> dict:
    """從歷史日收盤計算 N 日後報酬分佈。資料不足回 {}。"""
    if df is None or "Close" not in df.columns:
        return {}
    close = df["Close"].dropna()
    if len(close) < horizon + 40:
        return {"insufficient": True, "samples": max(0, len(close) - horizon)}

    fwd = (close.shift(-horizon) / close - 1.0).dropna() * 100.0
    arr = fwd.values
    n = len(arr)
    if n < 30:
        return {"insufficient": True, "samples": n}

    neg = arr[arr < 0]
    price = float(close.iloc[-1])
    p10 = float(np.percentile(arr, 10))
    p90 = float(np.percentile(arr, 90))
    expected = float(arr.mean())

    return {
        "horizon": horizon,
        "samples": n,
        "prob_up": round((arr > 0).mean() * 100, 1),
        "expected_return": round(expected, 2),
        "median_return": round(float(np.median(arr)), 2),
        "downside": round(float(neg.mean()), 2) if neg.size else 0.0,
        "p10": round(p10, 2),
        "p90": round(p90, 2),
        "target_low": round(price * (1 + p10 / 100), 2),
        "target_high": round(price * (1 + p90 / 100), 2),
        "expected_price": round(price * (1 + expected / 100), 2),
    }


def format_profit_space(ps: dict) -> str:
    """轉成 LINE/Discord 純文字（給沒有 AI 敘事時直接用，或當摘要）。"""
    if not ps or ps.get("insufficient"):
        return "獲利空間：歷史樣本不足，暫不評估。"
    return (
        f"獲利空間（持有約{ps['horizon']}交易日，依{ps['samples']}筆歷史）：\n"
        f"上漲機率 {ps['prob_up']}%｜期望報酬 {ps['expected_return']}%（中位數 {ps['median_return']}%）\n"
        f"樂觀情境 +{ps['p90']}%（目標 {ps['target_high']}）｜保守情境 {ps['p10']}%（{ps['target_low']}）\n"
        f"下檔風險（負報酬均值）{ps['downside']}%"
    )
