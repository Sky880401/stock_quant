"""
Line Bot Flask 應用程序
提供 webhook 端點接收 LINE 事件

部署方式:
- 開發: python line_webhook.py
- 生產: gunicorn line_webhook:app
"""

import hmac
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from flask import Flask, request, abort

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(dotenv_path=Path(PROJECT_ROOT) / '.env', override=True)

from line_bot import get_webhook_handler, get_feedback_manager
from linebot.exceptions import InvalidSignatureError

app = Flask(__name__)

# 配置
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
ADMIN_API_KEY = os.getenv('ADMIN_API_KEY')
webhook_handler = get_webhook_handler()
feedback_manager = get_feedback_manager()


def require_admin():
    """管理員端點認證: 需要 X-Admin-Key header 與 ADMIN_API_KEY 環境變數相符"""
    provided = request.headers.get('X-Admin-Key', '')
    if not ADMIN_API_KEY or not hmac.compare_digest(provided, ADMIN_API_KEY):
        abort(404)


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    接收 LINE webhook 事件
    
    LINE 平台應配置: https://yourserver.com/webhook
    """
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    try:
        webhook_handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ LINE Webhook 簽名驗證失敗")
        abort(400)
    except Exception as e:
        print(f"❌ Webhook 處理錯誤: {e}")
        abort(500)
    
    return 'OK', 200


@app.route('/health', methods=['GET'])
def health():
    """健康檢查端點"""
    return {'status': 'healthy'}, 200


@app.route('/feedback/stats', methods=['GET'])
def feedback_stats():
    """
    獲取反饋統計信息 (管理員端點)
    
    查詢: /feedback/stats (需 X-Admin-Key header)
    """
    require_admin()
    try:
        stats = {
            "total": len(feedback_manager.feedback_list),
            "by_type": {
                "bug": len([f for f in feedback_manager.feedback_list if f.get("type") == "bug"]),
                "improvement": len([f for f in feedback_manager.feedback_list if f.get("type") == "improvement"]),
                "question": len([f for f in feedback_manager.feedback_list if f.get("type") == "question"])
            },
            "by_status": {
                "new": len([f for f in feedback_manager.feedback_list if f.get("status") == "new"]),
                "processing": len([f for f in feedback_manager.feedback_list if f.get("status") == "processing"]),
                "resolved": len([f for f in feedback_manager.feedback_list if f.get("status") == "resolved"])
            }
        }
        return stats, 200
    except Exception as e:
        return {"error": str(e)}, 500


@app.route('/feedback/list', methods=['GET'])
def feedback_list():
    """
    列出最近的反饋 (管理員端點)
    
    查詢: /feedback/list?limit=10 (需 X-Admin-Key header)
    """
    require_admin()
    try:
        limit = max(1, min(request.args.get('limit', 20, type=int), 100))
        recent = feedback_manager.feedback_list[-limit:][::-1]  # 反轉以獲得最新的
        return {"feedback": recent}, 200
    except Exception as e:
        return {"error": str(e)}, 500


if __name__ == '__main__':
    print("🚀 LINE Bot Webhook 伺服器啟動")
    print(f"Webhook 端點: http://localhost:5000/webhook")
    print(f"健康檢查: http://localhost:5000/health")
    print(f"統計信息: http://localhost:5000/feedback/stats")
    
    # debug 模式會開啟 Werkzeug 互動式除錯器 (可遠端執行程式碼)，僅允許透過環境變數在本機開發時開啟
    # 生產環境請用 gunicorn (見 Dockerfile / Procfile)，開發伺服器只綁定本機
    debug_mode = os.getenv('DEBUG', 'false').lower() == 'true'
    app.run(host='127.0.0.1', port=5000, debug=debug_mode)
