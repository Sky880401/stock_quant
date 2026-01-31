import matplotlib
matplotlib.use('Agg')
import mplfinance as mpf
import pandas as pd
import os
import time
import matplotlib.font_manager as fm

# 1. 確保字型路徑絕對正確
FONT_PATH = "/root/stock_quant/utils/fonts/wqy-microhei.ttc"

# 檢查檔案是否存在
if not os.path.exists(FONT_PATH):
    print(f"❌ Font file not found at {FONT_PATH}")
    # Fallback: 嘗試使用系統字型 (如果有的話)
    FONT_PATH = None

# 2. 建立字型屬性物件
if FONT_PATH:
    my_font = fm.FontProperties(fname=FONT_PATH)
    font_name = my_font.get_name()
    # 註冊到 matplotlib
    fm.fontManager.addfont(FONT_PATH)
else:
    font_name = 'sans-serif' # 退路

def generate_stock_chart(ticker, df, strategy_params=None, output_dir="reports"):
    try:
        if df.empty or len(df) < 30: return None
        
        plot_df = df.tail(120).copy()
        
        # 3. 強制設定 rcParams (這是最暴力的解法)
        s = mpf.make_mpf_style(
            base_mpf_style='yahoo',
            marketcolors=mpf.make_marketcolors(up='r', down='g', inherit=True),
            rc={
                'font.family': font_name, 
                'axes.unicode_minus': False
            }
        )
        
        # 準備均線
        fast_ma = strategy_params.get('fast_ma', 20) if strategy_params else 20
        slow_ma = strategy_params.get('slow_ma', 60) if strategy_params else 60
        mav_lines = (fast_ma, slow_ma)
        
        # 準備副圖
        plots = []
        if 'Foreign' in plot_df.columns:
             # 注意：這裡的標題也會用到中文字型
             plots.append(mpf.make_addplot(plot_df['Foreign'], panel=1, color='blue', secondary_y=False, title="外資", ylabel='張數'))
        
        os.makedirs(output_dir, exist_ok=True)
        filename = f"chart_{ticker}_{int(time.time())}.png"
        output_path = os.path.join(output_dir, filename)
        
        # 繪圖
        mpf.plot(
            plot_df,
            type='candle',
            mav=mav_lines,
            volume=True, 
            addplot=plots,
            title=f"{ticker} (MA {fast_ma}/{slow_ma})",
            style=s,
            savefig=dict(fname=output_path, dpi=100, pad_inches=0.25),
            block=False
        )
        return output_path
    except Exception as e:
        print(f"❌ Plot Error: {e}")
        return None
