"""
Notification Integration Service.
Delivers real-time execution alerts and critical notifications via Telegram
and internal terminal event feeds.
"""
import time
from typing import Dict, Any, Optional
import requests
from backend.config.settings import settings
from backend.database.db import db


class NotificationService:
    def __init__(self):
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.enabled = settings.notifications_enabled

    def send_alert(self, title: str, message: str, level: str = "INFO", details: Optional[Dict[str, Any]] = None):
        """
        Dispatches alert to terminal logs and optional Telegram bot.
        """
        db.log_event(level, "NOTIFICATION", f"[{title}] {message}", details)

        if not self.enabled or not self.bot_token or not self.chat_id:
            return

        # Sanitize message to never expose credentials
        clean_msg = f"🔔 *CoinDCX Terminal: {title}*\n\n{message}\n\n_Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}_"
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": clean_msg,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            db.log_event("WARNING", "TELEGRAM_ERROR", f"Failed to send telegram notification: {e}")


# Global notification service instance
notifier = NotificationService()
