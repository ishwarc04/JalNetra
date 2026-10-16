import logging
from fastapi import APIRouter
from app.services.telegram import telegram_bot_service, TelegramStatusResponse

logger = logging.getLogger("jalnetra.api.telegram")
router = APIRouter(prefix="/telegram", tags=["Telegram Bot"])


@router.get(
    "/status",
    response_model=TelegramStatusResponse,
    summary="Get Telegram bot connection and configuration status",
    description="Returns whether the Telegram bot is enabled, configured, and actively connected. Never exposes tokens.",
)
def get_telegram_status() -> TelegramStatusResponse:
    return telegram_bot_service.get_status()
