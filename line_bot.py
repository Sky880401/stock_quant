"""
LINE Bot 反饋管理系統
自動將用戶反饋轉換為 GitHub Issues

功能:
- 接收 LINE 消息
- 解析反饋類型 (bug/建議/問題)
- 自動建立 GitHub Issue
- 追蹤反饋狀態
- 反垃圾和去重驗證
- 敏感詞過濾
"""

import os
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    FollowEvent, JoinEvent, PostbackEvent
)
import requests
from dotenv import load_dotenv

# 配置
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=Path(PROJECT_ROOT) / '.env', override=True)

LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO', 'yourusername/stock_quant')  # 格式: owner/repo

# 初始化
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 數據存儲
FEEDBACK_FILE = "data/line_feedback.json"
os.makedirs(os.path.dirname(FEEDBACK_FILE), exist_ok=True)


class ValidationManager:
    """驗證和反垃圾管理"""
    
    # 敏感詞詞典 (簡單版本)
    SENSITIVE_WORDS = [
        r'viagra', r'casino', r'lottery', r'porn', r'sex',
        r'(?:http|https)://[^\s]+',  # 過濾 URLs
    ]
    
    # 配置
    MIN_CONTENT_LENGTH = 10  # 最小內容長度
    MAX_CONTENT_LENGTH = 2000  # 最大內容長度 (避免超長訊息灌爆 GitHub Issue)
    MAX_FEEDBACK_PER_HOUR = 5  # 每小時最多反饋數
    DUPLICATE_TIMEFRAME = timedelta(hours=2)  # 去重時間框架
    RATE_LIMIT_ENABLED = True  # 是否啟用速率限制
    
    @classmethod
    def validate_message(cls, message: str, user_id: str, 
                        recent_feedback: List[Dict]) -> Tuple[bool, str]:
        """
        驗證消息
        
        返回: (是否有效, 錯誤信息)
        """
        # 1. 檢查長度
        if len(message.strip()) < cls.MIN_CONTENT_LENGTH:
            return False, f"消息過短 (最少 {cls.MIN_CONTENT_LENGTH} 字)"
        if len(message) > cls.MAX_CONTENT_LENGTH:
            return False, f"消息過長 (最多 {cls.MAX_CONTENT_LENGTH} 字)"
        
        # 2. 檢查敏感詞
        for pattern in cls.SENSITIVE_WORDS:
            if re.search(pattern, message, re.IGNORECASE):
                return False, "消息包含不允許的內容"
        
        # 3. 檢查重複
        is_duplicate, msg = cls._check_duplicate(message, user_id, recent_feedback)
        if is_duplicate:
            return False, msg
        
        # 4. 檢查速率限制
        if cls.RATE_LIMIT_ENABLED:
            is_rate_limited, msg = cls._check_rate_limit(user_id, recent_feedback)
            if is_rate_limited:
                return False, msg
        
        return True, ""
    
    @staticmethod
    def _check_duplicate(message: str, user_id: str, 
                        recent_feedback: List[Dict]) -> Tuple[bool, str]:
        """檢查重複反饋"""
        cutoff_time = datetime.now() - ValidationManager.DUPLICATE_TIMEFRAME
        
        for feedback in recent_feedback:
            if feedback.get("user_id") != user_id:
                continue
            
            # 檢查時間
            try:
                created = datetime.fromisoformat(feedback.get("created_at", ""))
                if created < cutoff_time:
                    continue
            except:
                continue
            
            # 檢查相似性 (雙向 substring 匹配；空描述不可視為重複)
            old_desc = feedback.get("description", "").lower().strip()
            new_desc = message.lower().strip()
            if old_desc and (old_desc in new_desc or new_desc in old_desc):
                return True, "您最近提交過類似的反饋，請稍後再試"
        
        return False, ""
    
    @staticmethod
    def _check_rate_limit(user_id: str, recent_feedback: List[Dict]) -> Tuple[bool, str]:
        """檢查用戶是否超過速率限制"""
        one_hour_ago = datetime.now() - timedelta(hours=1)
        count = 0
        
        for feedback in recent_feedback:
            if feedback.get("user_id") != user_id:
                continue
            
            try:
                created = datetime.fromisoformat(feedback.get("created_at", ""))
                if created >= one_hour_ago:
                    count += 1
            except:
                continue
        
        if count >= ValidationManager.MAX_FEEDBACK_PER_HOUR:
            return True, f"您已在最近一小時內提交 {count} 個反饋，請稍後再試"
        
        return False, ""


class FeedbackManager:
    """管理用戶反饋"""
    
    def __init__(self, storage_file: str = FEEDBACK_FILE):
        self.storage_file = storage_file
        self.feedback_list = self._load_feedback()
        self.validator = ValidationManager()
    
    def _load_feedback(self) -> List[Dict]:
        """載入已存儲的反饋"""
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def _save_feedback(self):
        """保存反饋到文件"""
        with open(self.storage_file, 'w', encoding='utf-8') as f:
            json.dump(self.feedback_list, f, ensure_ascii=False, indent=2)
    
    def get_recent_feedback(self, hours: int = 24) -> List[Dict]:
        """獲取最近 N 小時內的反饋"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent = []
        
        for feedback in self.feedback_list:
            try:
                created = datetime.fromisoformat(feedback.get("created_at", ""))
                if created >= cutoff_time:
                    recent.append(feedback)
            except:
                continue
        
        return recent
    
    def parse_feedback(self, message: str, user_id: str) -> Tuple[str, str, str]:
        """
        解析反饋消息
        
        支持的格式:
        - !bug 描述問題
        - !suggest 改進建議
        - !question 提出問題
        - bug: 描述問題
        - 改進: 改進建議
        - 問題: 提出問題
        
        返回: (反饋類型, 標題, 描述)
        """
        message = message.strip()
        feedback_type = "question"  # 預設類型
        title = ""
        description = message
        
        # 檢查命令格式
        if message.startswith("!bug "):
            feedback_type = "bug"
            description = message[5:].strip()
        elif message.startswith("!suggest "):
            feedback_type = "improvement"
            description = message[9:].strip()
        elif message.startswith("!question "):
            feedback_type = "question"
            description = message[10:].strip()
        elif message.startswith("bug:") or message.startswith("bug："):
            feedback_type = "bug"
            description = message.split(":", 1)[1].strip() if ":" in message else message[3:].strip()
        elif message.startswith("改進:") or message.startswith("改進："):
            feedback_type = "improvement"
            description = message.split(":", 1)[1].strip() if ":" in message else message[2:].strip()
        elif message.startswith("問題:") or message.startswith("問題："):
            feedback_type = "question"
            description = message.split(":", 1)[1].strip() if ":" in message else message[2:].strip()
        
        # 生成標題 (第一句或前50字)
        sentences = description.split('。')
        title = sentences[0][:50] if sentences else description[:50]
        if len(title) == 0:
            title = f"[{feedback_type}] 新反饋"
        
        return feedback_type, title, description
    
    def add_feedback(self, feedback_type: str, title: str, description: str, 
                    user_id: str, github_issue_url: Optional[str] = None) -> str:
        """添加反饋記錄"""
        feedback_id = f"fb_{len(self.feedback_list) + 1:04d}"
        
        feedback = {
            "id": feedback_id,
            "type": feedback_type,
            "title": title,
            "description": description,
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "github_issue_url": github_issue_url,
            "status": "new"
        }
        
        self.feedback_list.append(feedback)
        self._save_feedback()
        
        return feedback_id
    
    def get_feedback(self, feedback_id: str) -> Optional[Dict]:
        """獲取特定反饋"""
        for fb in self.feedback_list:
            if fb["id"] == feedback_id:
                return fb
        return None
    
    def update_feedback_status(self, feedback_id: str, status: str, github_url: Optional[str] = None):
        """更新反饋狀態"""
        for fb in self.feedback_list:
            if fb["id"] == feedback_id:
                fb["status"] = status
                if github_url:
                    fb["github_issue_url"] = github_url
                self._save_feedback()
                return True
        return False


class GitHubIssueManager:
    """管理 GitHub Issues"""
    
    def __init__(self, github_token: str, repo: str):
        """
        初始化
        
        Args:
            github_token: GitHub 個人訪問令牌
            repo: 倉庫地址 (格式: owner/repo)
        """
        self.github_token = github_token
        self.repo = repo
        self.api_url = f"https://api.github.com/repos/{repo}"
        self.headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json"
        }
    
    def create_issue(self, title: str, description: str, 
                    feedback_type: str = "question", 
                    user_id: str = "unknown") -> Optional[Dict]:
        """
        建立 GitHub Issue
        
        Args:
            title: Issue 標題
            description: Issue 描述
            feedback_type: 反饋類型 (bug/improvement/question)
            user_id: LINE 用戶 ID
        
        Returns:
            Issue 資訊字典，包含 url, number 等
        """
        try:
            # 決定標籤
            labels = self._get_labels(feedback_type)
            
            # 準備 Issue 內容 (user_id 僅保留遮罩後的前綴，避免在公開 repo 洩漏 LINE 用戶 ID)
            masked_user = f"{user_id[:6]}***" if user_id else "unknown"
            issue_body = f"""## 反饋信息

**來源**: LINE Bot (@{masked_user})
**類型**: {self._get_type_label(feedback_type)}  
**時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 描述

{description}

---

**系統信息**:
- 提交渠道: LINE Messaging API
- 自動化等級: 完全自動
"""
            
            payload = {
                "title": f"[{self._get_type_emoji(feedback_type)}] {title}",
                "body": issue_body,
                "labels": labels
            }
            
            response = requests.post(
                f"{self.api_url}/issues",
                headers=self.headers,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 201:
                issue_data = response.json()
                return {
                    "number": issue_data.get("number"),
                    "url": issue_data.get("html_url"),
                    "title": issue_data.get("title")
                }
            else:
                print(f"❌ GitHub API 錯誤: {response.status_code}")
                print(f"   {response.text}")
                return None
        
        except Exception as e:
            print(f"❌ 建立 Issue 失敗: {e}")
            return None
    
    @staticmethod
    def _get_type_emoji(feedback_type: str) -> str:
        """獲取類型表情符號"""
        emojis = {
            "bug": "🐛",
            "improvement": "✨",
            "question": "❓"
        }
        return emojis.get(feedback_type, "📝")
    
    @staticmethod
    def _get_type_label(feedback_type: str) -> str:
        """獲取類型標籤"""
        labels = {
            "bug": "Bug 報告",
            "improvement": "改進建議",
            "question": "用戶問題"
        }
        return labels.get(feedback_type, "其他")
    
    @staticmethod
    def _get_labels(feedback_type: str) -> List[str]:
        """根據類型返回 GitHub 標籤"""
        label_map = {
            "bug": ["bug", "from-line"],
            "improvement": ["enhancement", "from-line"],
            "question": ["question", "from-line"]
        }
        return label_map.get(feedback_type, ["from-line"])


# 全局實例
feedback_manager = FeedbackManager()
github_manager = None

# 初始化 GitHub Manager (如果配置了 Token)
if GITHUB_TOKEN:
    github_manager = GitHubIssueManager(GITHUB_TOKEN, GITHUB_REPO)


# LINE 事件處理
@handler.add(FollowEvent)
def handle_follow(event):
    """處理加好友事件"""
    user_id = event.source.user_id
    try:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(
                text="👋 歡迎使用 Stock Quant 反饋系統！\n\n"
                     "📝 支持的反饋格式:\n"
                     "• !bug 問題描述\n"
                     "• !suggest 改進建議\n"
                     "• !question 提出問題\n\n"
                     "💡 例子: !bug !train 命令參數解析有誤\n\n"
                     "所有反饋將自動轉換為 GitHub Issues 進行追蹤。"
            )
        )
    except LineBotApiError as e:
        print(f"❌ LINE API 錯誤: {e}")


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """處理文字消息"""
    user_id = event.source.user_id
    message_text = event.message.text
    
    try:
        # 1. 獲取最近的反饋以進行驗證
        recent_feedback = feedback_manager.get_recent_feedback(hours=24)
        
        # 2. 驗證消息
        is_valid, error_msg = ValidationManager.validate_message(
            message_text, user_id, recent_feedback
        )
        
        if not is_valid:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"❌ {error_msg}")
            )
            return
        
        # 3. 解析反饋
        feedback_type, title, description = feedback_manager.parse_feedback(message_text, user_id)
        
        # 4. 建立 GitHub Issue
        issue_url = None
        if github_manager:
            issue_result = github_manager.create_issue(
                title, description, feedback_type, user_id
            )
            if issue_result:
                issue_url = issue_result["url"]
                reply_text = (
                    f"✅ 反饋已提交！\n\n"
                    f"📌 類型: {github_manager._get_type_label(feedback_type)}\n"
                    f"🔗 GitHub Issue: #{issue_result['number']}\n"
                    f"🔍 查看: {issue_url}\n\n"
                    f"感謝您的反饋！團隊將盡快處理。"
                )
            else:
                reply_text = (
                    f"⚠️ 反饋已記錄，但 GitHub Issue 建立失敗。\n"
                    f"管理員將手動處理您的反饋。"
                )
        else:
            reply_text = (
                f"📝 反饋已記錄\n\n"
                f"類型: {github_manager._get_type_label(feedback_type) if github_manager else feedback_type}\n"
                f"感謝您的反饋！"
            )
        
        # 5. 保存反饋
        feedback_id = feedback_manager.add_feedback(
            feedback_type, title, description, user_id, issue_url
        )
        
        # 6. 回覆用戶
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        
        print(f"✅ 新反饋 {feedback_id}: {feedback_type} - {title}")
    
    except Exception as e:
        print(f"❌ 處理消息時出錯: {e}")
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ 處理出錯，請稍後重試。")
            )
        except:
            pass


def get_webhook_handler():
    """返回 webhook 處理器"""
    return handler


def get_feedback_manager():
    """返回反饋管理器"""
    return feedback_manager


if __name__ == "__main__":
    # 測試模式
    print("LINE Bot 反饋系統已就緒")
    print(f"GitHub 倉庫: {GITHUB_REPO}")
    print(f"反饋存儲: {FEEDBACK_FILE}")
