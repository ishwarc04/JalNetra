import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional, Set
from sqlalchemy import text

from app.core.config import settings
from app.db.database import SessionLocal
from app.services.ai.service import AIService
from app.services.telegram.client import TelegramClient
from app.services.telegram.models import TelegramMessage
from app.services.water_body_summary_service import WaterBodySummaryService

logger = logging.getLogger("jalnetra.services.telegram.handlers")


START_MESSAGE = """🌊 Welcome to JalNetra 2.0

I am the JalNetra monitoring assistant.

Current capabilities:
• Bot connectivity
• JalNetra AI connectivity
• Basic system status
• Registered water-body data access (/list, /waterbody)
• Latest satellite observation images

Use /help to see available commands."""

HELP_MESSAGE = """🌊 JalNetra Helper

Available commands:

/start
Start JalNetra Assistant

/help
Show available commands

/ping
Check bot connectivity

/status
Check JalNetra services

/list
List available water bodies

/waterbody <name>
Show water-body information and latest stored image

/ai <question>
Ask the JalNetra AI Assistant

ℹ️ Water-body information is read from the JalNetra database and stored observations."""

PING_MESSAGE = """🏓 JalNetra Telegram Bot is working.

Telegram API: OK
JalNetra Backend: OK"""


class TelegramCommandHandler:
    def __init__(
        self,
        client: TelegramClient,
        ai_service: Optional[AIService] = None,
        summary_service: Optional[WaterBodySummaryService] = None,
        db_factory: Optional[Callable] = None,
    ):
        self.client = client
        self.ai_service = ai_service or AIService()
        self.summary_service = summary_service
        self._db_factory = db_factory
        self._allowed_chat_ids: Optional[Set[str]] = self._parse_allowed_chat_ids()

    @contextmanager
    def _get_db(self):
        if self._db_factory:
            db = self._db_factory()
            try:
                yield db
            finally:
                db.close()
        else:
            with SessionLocal() as db:
                yield db

    def _parse_allowed_chat_ids(self) -> Optional[Set[str]]:
        raw = settings.TELEGRAM_ALLOWED_CHAT_IDS.strip()
        if not raw:
            return None
        ids = {cid.strip() for cid in raw.split(",") if cid.strip()}
        return ids if ids else None

    def is_chat_allowed(self, chat_id: int) -> bool:
        if self._allowed_chat_ids is None:
            return True
        return str(chat_id) in self._allowed_chat_ids

    def _check_db_status(self) -> str:
        try:
            with self._get_db() as db:
                db.execute(text("SELECT 1"))
            return "ONLINE"
        except Exception:
            return "OFFLINE"

    async def _send_water_body_summary_and_photo(self, chat_id: int, service: WaterBodySummaryService, wb_id: str):
        """Sends the structured summary card and, if available on disk, the latest visual photo."""
        summary = service.get_water_body_summary(wb_id)
        msg_text = service.format_telegram_summary_message(summary)
        await self.client.send_message(chat_id, msg_text)

        # Send photo if stored visual image exists locally
        if summary.has_stored_visual_image and summary.latest_image_path:
            p = Path(summary.latest_image_path)
            if p.exists() and p.is_file():
                try:
                    photo_bytes = p.read_bytes()
                    caption = (
                        f"🛰 Latest Visual — {summary.name}\n\n"
                        f"Observation: {summary.latest_observation_date}\n"
                        f"Cloud Cover: {summary.cloud_cover}\n\n"
                        f"This is the latest stored visual observation available in JalNetra."
                    )
                    await self.client.send_photo(
                        chat_id=chat_id,
                        photo_bytes=photo_bytes,
                        filename=p.name,
                        caption=caption,
                    )
                except Exception as exc:
                    logger.warning("Failed to send latest visual observation photo: %s", exc)

    async def handle_message(self, message: TelegramMessage):
        if not message.text:
            return

        chat_id = message.chat.id
        raw_text = message.text.strip()

        # Check authorization
        if not self.is_chat_allowed(chat_id):
            logger.warning("Rejected message from unauthorized Telegram chat ID: %s", chat_id)
            await self.client.send_message(
                chat_id, "🔒 Unauthorized access. Your chat ID is not permitted on this server."
            )
            return

        # Parse command
        parts = raw_text.split(maxsplit=1)
        command = parts[0].lower()
        if "@" in command:
            command = command.split("@")[0]

        args = parts[1].strip() if len(parts) > 1 else ""

        logger.info("Processing Telegram message from chat ID %s: '%s'", chat_id, command)

        if command == "/start":
            await self.client.send_message(chat_id, START_MESSAGE)

        elif command == "/help":
            await self.client.send_message(chat_id, HELP_MESSAGE)

        elif command == "/ping":
            await self.client.send_message(chat_id, PING_MESSAGE)

        elif command == "/status":
            ai_status = self.ai_service.get_status()
            ai_label = "CONFIGURED" if ai_status.configured else "NOT CONFIGURED"
            db_label = self._check_db_status()

            status_msg = (
                "JalNetra Status\n\n"
                "Backend: ONLINE\n"
                f"AI: {ai_label}\n"
                "Telegram: CONNECTED\n"
                f"Database: {db_label}"
            )
            await self.client.send_message(chat_id, status_msg)

        elif command == "/list":
            with self._get_db() as db:
                service = self.summary_service or WaterBodySummaryService(db)
                wbs = service.list_water_bodies()
                if not wbs:
                    await self.client.send_message(
                        chat_id,
                        "🌊 No water bodies are currently available in JalNetra.\n"
                        "Add a water body from the JalNetra application first.",
                    )
                    return

                lines = ["🌊 JalNetra Water Bodies\n"]
                for idx, wb in enumerate(wbs, start=1):
                    lines.append(f"{idx}. {wb.name}")

                lines.append("\nReply with:\n/waterbody <name>\n\nExample:\n/waterbody " + wbs[0].name)
                await self.client.send_message(chat_id, "\n".join(lines))

        elif command == "/waterbody":
            if not args:
                await self.client.send_message(
                    chat_id,
                    "Please specify a water body name.\nExample: /waterbody Chilika Lake\n\nUse /list to see all available water bodies.",
                )
                return

            with self._get_db() as db:
                service = self.summary_service or WaterBodySummaryService(db)
                matches = service.find_water_bodies(args)

                if not matches:
                    await self.client.send_message(
                        chat_id,
                        "❌ Water body not found.\n\nUse /list to see the available water bodies.",
                    )
                    return

                if len(matches) > 1:
                    lines = [f'I found multiple water bodies matching "{args}":\n']
                    for idx, wb in enumerate(matches, start=1):
                        lines.append(f"{idx}. {wb.name}")
                    lines.append(f"\nPlease use:\n/waterbody {matches[0].name}")
                    await self.client.send_message(chat_id, "\n".join(lines))
                    return

                target_wb = matches[0]
                await self._send_water_body_summary_and_photo(chat_id, service, target_wb.id)

        elif command == "/ai":
            if not args:
                await self.client.send_message(
                    chat_id,
                    "Please provide a question after /ai.\nExample: /ai What is JalNetra?",
                )
                return

            # Read-only guard: explicitly reject server command attempts
            forbidden_keywords = [
                "fetch satellite",
                "delete database",
                "run processing",
                "execute command",
                "rm ",
                "drop table",
            ]
            if any(kw in args.lower() for kw in forbidden_keywords):
                await self.client.send_message(
                    chat_id,
                    "⚠️ JalNetra AI is read-only in this version and cannot execute administrative server actions.",
                )
                return

            # Check if user mentioned any registered water body
            with self._get_db() as db:
                service = self.summary_service or WaterBodySummaryService(db)
                all_wbs = service.list_water_bodies()
                matched_wb = None
                for wb in all_wbs:
                    if wb.name.lower() in args.lower() or (wb.normalized_name and wb.normalized_name.lower() in args.lower()):
                        matched_wb = wb
                        break

                if matched_wb:
                    ai_svc = self.ai_service
                    if getattr(ai_svc, "db", None) is None:
                        ai_svc.db = db
                    try:
                        res = ai_svc.generate_analysis_response(
                            water_body_id=matched_wb.id,
                            observation_id=None,
                            question=args,
                        )
                        reply = f"🤖 JalNetra AI — {matched_wb.name}\n\n{res.answer}"
                    except Exception as exc:
                        logger.warning("AI water body analysis error: %s", exc)
                        reply = f"🤖 JalNetra AI\n\n{self.ai_service.generate_general_response(args)}"
                else:
                    ai_response = self.ai_service.generate_general_response(args)
                    reply = f"🤖 JalNetra AI\n\n{ai_response}"

            await self.client.send_message(chat_id, reply)

        else:
            # Short command / plain text lookup (Section 17):
            # If text matches a registered water body directly, show its summary!
            if not raw_text.startswith("/"):
                with self._get_db() as db:
                    service = self.summary_service or WaterBodySummaryService(db)
                    matches = service.find_water_bodies(raw_text)
                    if len(matches) == 1:
                        target_wb = matches[0]
                        await self._send_water_body_summary_and_photo(chat_id, service, target_wb.id)
                        return
                    elif len(matches) > 1:
                        lines = [f'I found multiple water bodies matching "{raw_text}":\n']
                        for idx, wb in enumerate(matches, start=1):
                            lines.append(f"{idx}. {wb.name}")
                        lines.append(f"\nPlease use:\n/waterbody {matches[0].name}")
                        await self.client.send_message(chat_id, "\n".join(lines))
                        return

            # Friendly fallback for unhandled command or unrecognized text
            await self.client.send_message(
                chat_id,
                "Unrecognized command. Type /help to see available commands, or /list to see registered water bodies.",
            )
