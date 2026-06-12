# 指標演算法課：基礎技術指標（原 main.py 同名函式，邏輯原樣搬入）
import pandas as pd


def analyze_chip(df):
    """三大法人籌碼：用『最新有公布的單一交易日』，單位為張(股數/1000)，
    並以該日當日漲跌判斷背離（修正過去用5日加總+標錯k張+用5日前比價的bug）。"""
    for col in ('Foreign', 'Trust', 'Dealer'):
        if col not in df.columns:
            df[col] = 0
    if len(df) < 2:
        return {"score": 0, "status": "Neutral", "reason": "無籌碼資料"}
    inst = df[['Foreign', 'Trust', 'Dealer']].fillna(0)
    # 最新日盤中可能尚未公布(全0)，往前找最近「有資料」的交易日
    idx = None
    for i in range(len(df) - 1, max(-1, len(df) - 6), -1):
        if (inst.iloc[i] != 0).any():
            idx = i; break
    if idx is None:
        return {"score": 0, "status": "Neutral", "reason": "近日無法人資料"}

    lots = lambda v: int(round(v / 1000))          # 股 → 張
    fl, tl, dl = lots(inst['Foreign'].iloc[idx]), lots(inst['Trust'].iloc[idx]), lots(inst['Dealer'].iloc[idx])
    date_str = df.index[idx].strftime('%m/%d')
    prev_close = df['Close'].iloc[idx - 1] if idx > 0 else df['Close'].iloc[idx]
    chg = df['Close'].iloc[idx] - prev_close
    chg_pct = (chg / prev_close * 100) if prev_close else 0.0

    def fmt(l, who):
        return f"{who}買超{l}張" if l > 0 else (f"{who}賣超{abs(l)}張" if l < 0 else f"{who}持平")

    score = 0.0
    reasons = [f"{date_str} {fmt(fl,'外資')}、{fmt(tl,'投信')}、{fmt(dl,'自營')}"]
    if fl > 3000: score += 1
    elif fl < -3000: score -= 1
    elif fl > 500: score += 0.4
    elif fl < -500: score -= 0.4
    if tl > 1000: score += 0.7
    elif tl < -1000: score -= 0.7
    if dl > 1000: score += 0.3
    elif dl < -1000: score -= 0.3

    inst_net = fl + tl
    if chg > 0 and inst_net < 0:
        reasons.append("⚠️當日價漲但法人賣超(背離)"); score -= 0.5
    elif chg < 0 and inst_net > 0:
        reasons.append("當日價跌但法人買超(止穩訊號)"); score += 0.3
    reasons.append(f"當日{'漲' if chg >= 0 else '跌'}{abs(round(chg,2))}元({round(chg_pct,1)}%)")
    status = "Bullish" if score > 0.5 else ("Bearish" if score < -0.5 else "Neutral")
    return {"score": round(score, 2), "status": status, "reason": " | ".join(reasons)}

def calculate_macd_signal(df):
    try:
        exp12 = df['Close'].ewm(span=12, adjust=False).mean()
        exp26 = df['Close'].ewm(span=26, adjust=False).mean()
        macd = exp12 - exp26
        signal = macd.ewm(span=9, adjust=False).mean()
        curr_macd = macd.iloc[-1]; curr_sig = signal.iloc[-1]
        prev_macd = macd.iloc[-2]; prev_sig = signal.iloc[-2]
        status = "NEUTRAL"
        if curr_macd > curr_sig: status = "BUY" if prev_macd <= prev_sig else "HOLD BUY"
        elif curr_macd < curr_sig: status = "SELL" if prev_macd >= prev_sig else "HOLD SELL"
        return status, curr_macd - curr_sig
    except: return "NEUTRAL", 0.0

def calculate_rsi_series(df, period=14):
    """回傳整條 RSI 序列（Wilder 平滑），供去抖動使用。"""
    try:
        delta = df['Close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-9)
        return 100 - (100 / (1 + rs))
    except Exception:
        return None

def calculate_atr(df, period=14):
    try:
        high = df['High']; low = df['Low']; close = df['Close'].shift(1)
        tr = pd.concat([high-low, (high-close).abs(), (low-close).abs()], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().iloc[-1]
        return atr
    except: return df['Close'].iloc[-1] * 0.03
