# 升級為 Python 3.10 以獲得更好支援
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# 生產環境使用 gunicorn，不可用 Flask 開發伺服器 (debug 模式有 RCE 風險)
CMD ["gunicorn", "line_webhook:app", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "120"]
