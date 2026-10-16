import json
import logging
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger("jalnetra.services.telegram")


class TelegramClient:
    """
    Lightweight, asynchronous Telegram Bot API client using httpx.
    Keeps token strictly internal and never exposes or logs it.
    """

    def __init__(self, token: Optional[str] = None):
        self._token = (token or settings.TELEGRAM_BOT_TOKEN).strip()
        self._base_url = f"https://api.telegram.org/bot{self._token}" if self._token else ""
        self._http_client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        return bool(self._token)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=45.0))
        return self._http_client

    async def close(self):
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def get_me(self) -> Optional[Dict[str, Any]]:
        if not self.is_configured:
            return None
        url = f"{self._base_url}/getMe"
        client = await self._get_client()
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data.get("result")
            logger.warning("Telegram getMe responded with status %s", resp.status_code)
            return None
        except Exception as e:
            logger.warning("Telegram getMe connection failed: %s", type(e).__name__)
            return None

    async def get_updates(self, offset: Optional[int] = None, timeout: int = 20) -> List[Dict[str, Any]]:
        if not self.is_configured:
            return []
        url = f"{self._base_url}/getUpdates"
        params: Dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset

        client = await self._get_client()
        try:
            resp = await client.get(url, params=params, timeout=timeout + 10.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return data.get("result", [])
            logger.warning("Telegram getUpdates returned status %s", resp.status_code)
            return []
        except httpx.TimeoutException:
            # Normal in long-polling when no updates arrived within timeout
            return []
        except Exception as e:
            logger.warning("Telegram getUpdates error: %s", type(e).__name__)
            return []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.is_configured:
            return False
        url = f"{self._base_url}/sendMessage"
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        client = await self._get_client()
        try:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return bool(data.get("ok"))
            logger.warning("Telegram sendMessage returned status %s: %s", resp.status_code, resp.text)
            return False
        except Exception as e:
            logger.warning("Telegram sendMessage failed: %s", type(e).__name__)
            return False

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> bool:
        if not self.is_configured:
            return False
        url = f"{self._base_url}/answerCallbackQuery"
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text

        client = await self._get_client()
        try:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return bool(data.get("ok"))
            return False
        except Exception as e:
            logger.warning("Telegram answerCallbackQuery failed: %s", type(e).__name__)
            return False

    async def send_photo(
        self,
        chat_id: int,
        photo_bytes: bytes,
        filename: str = "observation.jpg",
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.is_configured:
            return False
        url = f"{self._base_url}/sendPhoto"
        data: Dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else str(reply_markup)

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
        content_type = "image/png" if ext == "png" else "image/jpeg"
        files = {"photo": (filename, photo_bytes, content_type)}

        client = await self._get_client()
        try:
            resp = await client.post(url, data=data, files=files, timeout=45.0)
            if resp.status_code == 200:
                body = resp.json()
                return bool(body.get("ok"))
            logger.warning("Telegram sendPhoto returned status %s: %s", resp.status_code, resp.text)
            return False
        except Exception as e:
            logger.warning("Telegram sendPhoto failed: %s", type(e).__name__)
            return False
