# 風控課：法人避雷警示（原 main.py 的 inst_avoid_alert，邏輯原樣搬入）

# === 法人避雷（inst avoidance alert）===
# 校準（2026-06-10，寬版 panel 340檔×27月，與 quant 因子 inst 同定義）：
#   ratio = 近20日(外資+投信)淨買股數 / 近20日成交量
#   全市場 pooled 分布底部20%門檻 ≈ -0.076、底部10% ≈ -0.132
#   實證：底部20%組之後20日平均落後全體 -1.61%/月（t=-3.44、78%月份落後）
#   ⚠️ 性質＝統計性「避雷」提示（被法人重砍的股票之後偏弱），非個股方向預測；
#   做多端無套利價值（top quintile 不贏大盤），故只做負面警示、不調分數。
INST_AVOID_P20 = -0.076
INST_AVOID_P10 = -0.132


def inst_avoid_alert(df):
    """回 {level: none/heavy/extreme/no_data, inst_20d_ratio, meaning}。缺法人資料(如美股)回 no_data。"""
    try:
        if "Foreign" not in df.columns or "Volume" not in df.columns:
            return {"level": "no_data"}
        trust = df["Trust"].fillna(0) if "Trust" in df.columns else 0
        inst_net = df["Foreign"].fillna(0) + trust
        ratio = inst_net.rolling(20).sum() / df["Volume"].rolling(20).sum().replace(0, float("nan"))
        v = ratio.dropna()
        if not len(v):
            return {"level": "no_data"}
        x = float(v.iloc[-1])
        level = "extreme" if x <= INST_AVOID_P10 else ("heavy" if x <= INST_AVOID_P20 else "none")
        out = {"level": level, "inst_20d_ratio": round(x, 4)}
        if level != "none":
            pct = "10%" if level == "extreme" else "20%"
            out["meaning"] = ("近20日法人(外資+投信)賣超強度落在全市場歷史底部" + pct +
                              "；此族群歷史上之後一個月平均落後大盤約1.6%、78%的月份落後。"
                              "這是統計性避雷提示，不是方向預測。")
        return out
    except Exception:
        return {"level": "no_data"}
