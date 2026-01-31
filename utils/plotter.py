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
        
        # 準備數據
        calc_df = df.copy()
        calc_df['MA5'] = calc_df['Close'].rolling(window=5).mean()
        calc_df['MA20'] = calc_df['Close'].rolling(window=20).mean()
        calc_df['MA60'] = calc_df['Close'].rolling(window=60).mean()
        calc_df['MA240'] = calc_df['Close'].rolling(window=240).mean()
        
        plot_df = calc_df.tail(120).copy()
        if 'Foreign' in plot_df.columns:
            plot_df['Foreign'] = plot_df['Foreign'].fillna(0)
        
        # 樣式
        s = mpf.make_mpf_style(
            base_mpf_style='yahoo',
            marketcolors=mpf.make_marketcolors(up='r', down='g', inherit=True),
            rc={'font.family': font_name, 'axes.unicode_minus': False}
        )
        
        # 圖層
        ap = [
            mpf.make_addplot(plot_df['MA5'], color='magenta', width=1.0, label='MA5 (週)'),
            mpf.make_addplot(plot_df['MA20'], color='orange', width=1.2, label='MA20 (月)'),
            mpf.make_addplot(plot_df['MA60'], color='green', width=1.5, label='MA60 (季)'),
            mpf.make_addplot(plot_df['MA240'], color='blue', width=1.5, label='MA240 (年)')
        ]
        
        if 'Foreign' in plot_df.columns and plot_df['Foreign'].abs().sum() > 0:
             foreign_data = plot_df['Foreign']
             colors = ['red' if v > 0 else 'green' for v in foreign_data]
             ap.append(mpf.make_addplot(
                 foreign_data, 
                 panel=2, 
                 type='bar', 
                 color=colors, 
                 secondary_y=False, 
                 ylabel='外資'
             ))

        os.makedirs(output_dir, exist_ok=True)
        filename = f"chart_{ticker}_{int(time.time())}.png"
        output_path = os.path.join(output_dir, filename)
        
        # [核心修改] 使用 returnfig=True 獲取 fig 物件，手動設置標題
        fig, axes = mpf.plot(
            plot_df,
            type='candle',
            volume=True, 
            addplot=ap,
            style=s,
            returnfig=True, # 關鍵：回傳 figure 物件
            panel_ratios=(2, 1, 1) if len(ap) > 4 else (2, 1),
            datetime_format='%Y-%m-%d',
            tight_layout=True,
            figsize=(10, 8) # 調整畫布大小
        )
        
        # 手動設置標題，y=1.02 代表在畫布最上緣再往上一點點
        title_text = f"{ticker} 技術分析圖"
        fig.suptitle(title_text, fontproperties=my_font, fontsize=16, y=0.95)
        
        # 存檔
        fig.savefig(output_path, dpi=100, bbox_inches='tight')
        
        # 釋放記憶體 (重要)
        matplotlib.pyplot.close(fig)
        
        return output_path
    except Exception as e:
        print(f"❌ Plot Error: {e}")
        return None
