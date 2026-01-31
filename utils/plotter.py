import matplotlib
matplotlib.use('Agg')
import mplfinance as mpf
import pandas as pd
import os
import time
import matplotlib.font_manager as fm

# 字型設定
FONT_PATH = "/root/stock_quant/utils/fonts/wqy-microhei.ttc"
if os.path.exists(FONT_PATH):
    fm.fontManager.addfont(FONT_PATH)
    my_font = fm.FontProperties(fname=FONT_PATH)
    font_name = my_font.get_name()
else:
    font_name = 'sans-serif'

def generate_stock_chart(ticker, df, strategy_params=None, output_dir="reports"):
    try:
        if df.empty or len(df) < 30: return None
        
        plot_df = df.tail(120).copy()
        
        # [修復] 清洗數據：將外資數據的 NaN 填補為 0，防止繪圖崩潰或縮放錯誤
        if 'Foreign' in plot_df.columns:
            plot_df['Foreign'] = plot_df['Foreign'].fillna(0)
        
        s = mpf.make_mpf_style(
            base_mpf_style='yahoo',
            marketcolors=mpf.make_marketcolors(up='r', down='g', inherit=True),
            rc={'font.family': font_name, 'axes.unicode_minus': False}
        )
        
        fast_ma = strategy_params.get('fast_ma', 20) if strategy_params else 20
        slow_ma = strategy_params.get('slow_ma', 60) if strategy_params else 60
        mav_lines = (fast_ma, slow_ma)
        
        plots = []
        panel_ratios = (2, 1) # 預設只畫 K線(2) + 成交量(1)
        
        # [優化] 只有當外資數據有意義 (不全為0) 時才畫副圖
        if 'Foreign' in plot_df.columns and plot_df['Foreign'].abs().sum() > 0:
             foreign_data = plot_df['Foreign']
             colors = ['red' if v > 0 else 'green' for v in foreign_data]
             
             # [修復] 移除 title 參數，解決文字亂飄問題。改用 ylabel 標示
             plots.append(mpf.make_addplot(
                 foreign_data, 
                 panel=2, 
                 type='bar', 
                 color=colors, 
                 secondary_y=False, 
                 ylabel='Foreign(Vol)' # 使用 Y 軸標籤代替標題
             ))
             panel_ratios = (2, 1, 1) # 開啟第三個面板
        
        os.makedirs(output_dir, exist_ok=True)
        filename = f"chart_{ticker}_{int(time.time())}.png"
        output_path = os.path.join(output_dir, filename)
        
        mpf.plot(
            plot_df,
            type='candle',
            mav=mav_lines,
            volume=True, 
            addplot=plots,
            title=f"{ticker} (MA {fast_ma}/{slow_ma})",
            style=s,
            savefig=dict(fname=output_path, dpi=100, pad_inches=0.25),
            block=False,
            panel_ratios=panel_ratios,
            datetime_format='%m-%d',
            tight_layout=True # 自動調整佈局
        )
        return output_path
    except Exception as e:
        print(f"❌ Plot Error: {e}")
        return None
