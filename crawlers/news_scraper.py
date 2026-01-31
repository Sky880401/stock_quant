import requests
from bs4 import BeautifulSoup

def fetch_yahoo_news(stock_id):
    """
    抓取 Yahoo 股市個股新聞標題
    """
    url = f"https://tw.stock.yahoo.com/quote/{stock_id}/news"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code != 200: return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        headlines = []
        for item in soup.find_all('h3'):
            title = item.text.strip()
            if len(title) > 5: headlines.append(title)
                
        return headlines[:5]
    except Exception as e:
        print(f"News Crawler Error: {e}")
        return []
