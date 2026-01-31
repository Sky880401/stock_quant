import matplotlib
matplotlib.use('Agg') # 強制非互動模式
import mplfinance as mpf
import pandas as pd
import os
import time

def generate_stock_chart(ticker, df, strategy_params=None, output_dir="reports"):
    """
    繪製 K 線圖 + MA + 籌碼副圖 (修復版)
    """
    try:
        if df.empty or len(df) < 30: return None
        
        # 截取最近 120 天
        plot_df = df.tail(120).copy()
        
        # 準備均線
        fast_ma = strategy_params.get('fast_ma', 20) if strategy_params else 20
        slow_ma = strategy_params.get('slow_ma', 60) if strategy_params else 60
        mav_lines = (fast_ma, slow_ma)
        
        # 準備副圖 (外資)
        plots = []
        if 'Foreign' in plot_df.columns:
             # 外資 (藍色)
             plots.append(mpf.make_addplot(plot_df['Foreign'], panel=1, color='blue', secondary_y=False, title="Foreign", ylabel='Vol'))
        
        # 存檔路徑
        os.makedirs(output_dir, exist_ok=True)
        filename = f"chart_{ticker}_{int(time.time())}.png"
        output_path = os.path.join(output_dir, filename)
        
        # 繪圖 (移除自定義 style 物件，直接用字串 'yahoo')
        mpf.plot(
            plot_df,
            type='candle',
            mav=mav_lines,
            volume=True, 
            addplot=plots,
            title=f"{ticker} (MA {fast_ma}/{slow_ma})",
            style='yahoo', # [修正] 直接使用內建樣式名稱
            savefig=dict(fname=output_path, dpi=100, pad_inches=0.25),
            block=False
        )
        
        return output_path
    except Exception as e:
        print(f"❌ Plot Error: {e}")
        return None
