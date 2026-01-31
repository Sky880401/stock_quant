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
        
        calc_df = df.copy()
        calc_df['MA5'] = calc_df['Close'].rolling(window=5).mean()
        calc_df['MA20'] = calc_df['Close'].rolling(window=20).mean()
        calc_df['MA60'] = calc_df['Close'].rolling(window=60).mean()
        calc_df['MA240'] = calc_df['Close'].rolling(window=240).mean()
        
        plot_df = calc_df.tail(120).copy()
        if 'Foreign' in plot_df.columns:
            plot_df['Foreign'] = plot_df['Foreign'].fillna(0)
        
        s = mpf.make_mpf_style(
            base_mpf_style='yahoo',
            marketcolors=mpf.make_marketcolors(up='r', down='g', inherit=True),
            rc={'font.family': font_name, 'axes.unicode_minus': False}
        )
        
        ap = [
            mpf.make_addplot(plot_df['MA5'], color='magenta', width=1.0, label='MA5 (W)'),
            mpf.make_addplot(plot_df['MA20'], color='orange', width=1.2, label='MA20 (M)'),
            mpf.make_addplot(plot_df['MA60'], color='green', width=1.5, label='MA60 (Q)'),
            mpf.make_addplot(plot_df['MA240'], color='blue', width=1.5, label='MA240 (Y)')
        ]
        
        panel_ratios = (3, 1) # 預設比例
        
        if 'Foreign' in plot_df.columns and plot_df['Foreign'].abs().sum() > 0:
             foreign_data = plot_df['Foreign']
             colors = ['red' if v > 0 else 'green' for v in foreign_data]
             ap.append(mpf.make_addplot(
                 foreign_data, panel=2, type='bar', color=colors, 
                 secondary_y=False, ylabel='Foreign'
             ))
             # [優化] 調整比例：主圖 3，成交量 1.5，外資 1.5 (讓副圖大一點)
             panel_ratios = (3, 1.5, 1.5)

        os.makedirs(output_dir, exist_ok=True)
        filename = f"chart_{ticker}_{int(time.time())}.png"
        output_path = os.path.join(output_dir, filename)
        
        fig, axes = mpf.plot(
            plot_df,
            type='candle',
            volume=True, 
            addplot=ap,
            style=s,
            returnfig=True,
            panel_ratios=panel_ratios,
            datetime_format='%Y-%m-%d',
            figsize=(10, 10) # [優化] 增加高度，讓圖表更舒展
        )
        
        title_text = f"{ticker} Technical Chart"
        fig.suptitle(title_text, fontproperties=my_font, fontsize=18, y=0.96)
        fig.tight_layout(rect=[0, 0, 1, 0.94]) # 留出頂部空間
        
        fig.savefig(output_path, dpi=100)
        matplotlib.pyplot.close(fig)
        
        return output_path
    except Exception as e:
        print(f"❌ Plot Error: {e}")
        return None
