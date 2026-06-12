# 回測演算法課：Kelly 準則資金管理（原 main.py 同名函式，邏輯原樣搬入）


def calculate_kelly_position(win_rate, avg_win_ratio, avg_loss_ratio, max_position=100):
    """
    Kelly準則資金管理：kelly_fraction = (p * b - q) / b
    其中: p=勝率, b=贏損比, q=敗率(1-p)
    使用Kelly的25% (四分之一Kelly) 保守策略
    """
    # 資料不足 → 保守給一成
    if not (0 < win_rate < 1) or avg_win_ratio <= 0 or avg_loss_ratio <= 0:
        return max_position * 0.10

    loss_rate = 1.0 - win_rate
    b = avg_win_ratio / avg_loss_ratio
    full_kelly = (win_rate * b - loss_rate) / b   # 完整 Kelly 比例（可能為負＝不該進場）
    if full_kelly <= 0:
        return 0.0
    # 四分之一 Kelly（保守），單檔上限 25% 資金；只折扣一次
    quarter_kelly = min(full_kelly * 0.25, 0.25)
    return round(quarter_kelly * max_position, 1)
