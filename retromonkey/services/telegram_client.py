"""Telegram Bot API client — lightweight HTTP wrapper using requests."""

import logging

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramClient:
    """Minimal Telegram Bot API client for sending alerts and handling callbacks."""

    def __init__(self, config=None):
        self._config = config

    @property
    def _token(self):
        if self._config:
            return self._config.get("TELEGRAM_BOT_TOKEN", "")
        from flask import current_app
        return current_app.config.get("TELEGRAM_BOT_TOKEN", "")

    @property
    def _chat_id(self):
        if self._config:
            return self._config.get("TELEGRAM_CHAT_ID", "")
        from flask import current_app
        return current_app.config.get("TELEGRAM_CHAT_ID", "")

    @property
    def is_configured(self) -> bool:
        return bool(self._token and self._chat_id)

    def _url(self, method: str) -> str:
        return API_BASE.format(token=self._token, method=method)

    def send_message(self, text: str, parse_mode: str = "HTML",
                     reply_markup: dict | None = None) -> dict:
        """Send a message to the configured chat.

        Returns the Telegram API response dict.
        """
        if not self.is_configured:
            logger.warning("Telegram not configured — skipping message")
            return {"ok": False, "error": "not configured"}

        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            resp = requests.post(self._url("sendMessage"), json=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                logger.error("Telegram sendMessage failed: %s", data.get("description"))
            return data
        except Exception as exc:
            logger.error("Telegram send error: %s", exc)
            return {"ok": False, "error": str(exc)}

    def set_webhook(self, url: str) -> dict:
        """Register a webhook URL for receiving updates."""
        if not self._token:
            return {"ok": False, "error": "no token"}
        try:
            resp = requests.post(self._url("setWebhook"), json={"url": url}, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("Telegram setWebhook error: %s", exc)
            return {"ok": False, "error": str(exc)}

    def delete_webhook(self) -> dict:
        """Remove the current webhook."""
        if not self._token:
            return {"ok": False, "error": "no token"}
        try:
            resp = requests.post(self._url("deleteWebhook"), timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("Telegram deleteWebhook error: %s", exc)
            return {"ok": False, "error": str(exc)}

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> dict:
        """Acknowledge a callback query (inline button press)."""
        if not self._token:
            return {"ok": False, "error": "no token"}
        try:
            resp = requests.post(self._url("answerCallbackQuery"), json={
                "callback_query_id": callback_query_id,
                "text": text,
            }, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("Telegram answerCallbackQuery error: %s", exc)
            return {"ok": False, "error": str(exc)}

    def get_me(self) -> dict:
        """Get bot info — useful for verifying token."""
        if not self._token:
            return {"ok": False, "error": "no token"}
        try:
            resp = requests.get(self._url("getMe"), timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
