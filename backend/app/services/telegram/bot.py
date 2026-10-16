import asyncio
import logging
from typing import Optional

from app.core.config import settings
from app.services.telegram.client import TelegramClient
from app.services.telegram.handlers import TelegramCommandHandler
from app.services.telegram.models import TelegramStatusResponse, TelegramUpdate

logger = logging.getLogger("jalnetra.services.telegram.bot")


class TelegramBotService:
    """
    Manages Telegram bot lifecycle, authentication, and long-polling background worker.
    Ensures connectivity issues or missing configuration never crash the FastAPI application.
    """

    def __init__(self, client: Optional[TelegramClient] = None):
        self.client = client or TelegramClient()
        self.handler = TelegramCommandHandler(self.client)
        self._running: bool = False
        self._connected: bool = False
        self._bot_username: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._offset: Optional[int] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def bot_username(self) -> Optional[str]:
        return self._bot_username

    def get_status(self) -> TelegramStatusResponse:
        enabled = settings.TELEGRAM_ENABLED
        configured = bool(settings.TELEGRAM_BOT_TOKEN.strip())
        return TelegramStatusResponse(
            enabled=enabled,
            configured=configured and enabled,
            connected=self._connected and enabled,
            bot_username=self._bot_username or settings.TELEGRAM_BOT_USERNAME,
        )

    async def start(self):
        if not settings.TELEGRAM_ENABLED:
            logger.info("Telegram service is disabled in configuration.")
            return

        token = settings.TELEGRAM_BOT_TOKEN.strip()
        if not token:
            logger.info("Telegram service is enabled, but TELEGRAM_BOT_TOKEN is not configured.")
            return

        logger.info("Initializing Telegram bot connection...")
        me = await self.client.get_me()
        if not me:
            logger.warning("Telegram bot authentication failed: invalid token or unreachable Telegram API.")
            self._connected = False
            return

        self._connected = True
        self._bot_username = me.get("username", settings.TELEGRAM_BOT_USERNAME)
        logger.info("Telegram bot authenticated successfully as @%s", self._bot_username)

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.client.close()
        self._connected = False
        logger.info("Telegram bot polling stopped.")

    async def _poll_loop(self):
        logger.info("Telegram long-polling loop started.")
        while self._running:
            try:
                raw_updates = await self.client.get_updates(offset=self._offset, timeout=15)
                for item in raw_updates:
                    update_id = item.get("update_id")
                    if update_id is not None:
                        self._offset = update_id + 1

                    try:
                        update = TelegramUpdate.model_validate(item)
                        if update.message:
                            await self.handler.handle_message(update.message)
                    except Exception as e:
                        logger.error("Error processing Telegram update: %s", e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Unexpected error in Telegram polling: %s. Reconnecting in 3s...", type(e).__name__)
                await asyncio.sleep(3.0)


# Global singleton instance for app lifespan integration
telegram_bot_service = TelegramBotService()
