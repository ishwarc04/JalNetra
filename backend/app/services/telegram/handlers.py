import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Set, Dict, Any, List
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models.water_body import WaterBody
from app.services.ai.service import AIService
from app.services.satellite.image_resolver import ObservationImageResolver
from app.services.telegram.client import TelegramClient
from app.services.telegram.models import TelegramMessage, TelegramCallbackQuery
from app.services.telegram.intent_service import (
    TelegramIntentService,
    TelegramIntent,
    IntentResult,
)
from app.services.water_body_summary_service import (
    WaterBodySummaryService,
    WaterBodyTelegramSummary,
)

logger = logging.getLogger("jalnetra.services.telegram.handlers")


START_MESSAGE = """🌊 Welcome to JalNetra 2.0

I am your JalNetra water-body monitoring assistant.

You can ask me naturally in plain text:
• "Is the water at Phewa Tal drinkable?"
• "Is this water toxic?"
• "Can I bathe here?"
• "Will the water level increase?"
• "Will it rain tomorrow?"
• "Show me the latest image of Phewa Tal"
• "Where is Phewa Tal?"
• "How is the water quality of Harsul Reservoir?"
• "List all water bodies"

Commands:
/list — List registered water bodies
/waterbody <name> — Full telemetry & latest image
/status — Check system status
/ping — Bot connectivity check
/ai <question> — Ask AI Assistant
/help — Show commands & usage"""

HELP_MESSAGE = """🌊 JalNetra Helper

You can talk to me naturally or use commands:

Natural Language Examples:
• "Is the water drinkable?"
• "Is this water toxic?"
• "Can I bathe here?"
• "Is the water safe?"
• "Will the water level increase?"
• "Will it rain?"
• "Show me its latest image"
• "Where is Phewa Tal?"
• "How is the water quality of Harsul Reservoir?"
• "Show all water bodies"

Available Commands:
/start — Start JalNetra Assistant
/help — Show available commands & guide
/ping — Check bot connectivity
/status — Check JalNetra services
/list — List available water bodies
/waterbody <name> — Show water-body information and latest stored image
/ai <question> — Ask the JalNetra AI Assistant

ℹ️ Water-body information is read directly from Sentinel-2 satellite observations, Open-Meteo forecasts, and JalNetra local storage."""

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
        intent_service: Optional[TelegramIntentService] = None,
    ):
        self.client = client
        self.ai_service = ai_service or AIService()
        self.summary_service = summary_service
        self._db_factory = db_factory
        self.intent_service = intent_service or TelegramIntentService(ai_service=self.ai_service)
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

    def _build_water_body_inline_keyboard(
        self, wb_id: str, google_maps_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Builds interactive Telegram inline keyboard for quick exploration."""
        row1: List[Dict[str, str]] = [
            {"text": "📸 Latest Image", "callback_data": f"wb_img:{wb_id}"},
        ]
        if google_maps_url:
            row1.append({"text": "🗺 Location", "url": google_maps_url})

        row2: List[Dict[str, str]] = [
            {"text": "💧 Water Quality", "callback_data": f"wb_qual:{wb_id}"},
            {"text": "🌦 Weather", "callback_data": f"wb_weath:{wb_id}"},
            {"text": "📊 Monitoring", "callback_data": f"wb_mon:{wb_id}"},
        ]
        return {"inline_keyboard": [row1, row2]}

    # ─── Formatter Helpers ────────────────────────────────────────────────────

    def _format_drinkability_response(self, summary: WaterBodyTelegramSummary) -> str:
        """Section 4: Strict drinking-water safety disclaimer with scientific limitations."""
        lines = [
            f"💧 {summary.name} — Drinking Water Assessment",
            "",
            "JalNetra cannot certify this water as safe for drinking.",
            "",
            "Satellite observations can identify optical water-quality",
            "signals such as turbidity/sediment or algal-related changes,",
            "but they cannot detect pathogens, bacteria, viruses or many",
            "chemical contaminants.",
            "",
            "Current JalNetra status:",
            "🟡 No laboratory potability result available",
            "",
            "For drinking-water safety, laboratory testing or an official",
            "water-quality authority is required.",
        ]
        if summary.water_quality_label and any(
            w in summary.water_quality_label.upper() for w in ["POOR", "CONCERN", "HIGH", "WATCH", "ELEVATED", "ANOMALY"]
        ):
            lines.extend([
                "",
                "⚠️ Recent optical indicators show conditions that may warrant further water-quality investigation.",
                "",
                "This is NOT a laboratory toxicity or potability measurement.",
            ])
        return "\n".join(lines)

    def _format_toxicity_response(self, summary: WaterBodyTelegramSummary) -> str:
        """Section 5: Strict toxicity assessment without falsely claiming laboratory data."""
        lines = [
            f"☣️ {summary.name} — Toxicity Assessment",
            "",
            "JalNetra cannot determine water toxicity from satellite imagery alone.",
            "",
            f"No laboratory toxicity/chemical-contaminant result is currently available for {summary.name}.",
            "",
            "JalNetra can monitor optical indicators such as:",
            "• turbidity/sediment proxy",
            "• chlorophyll-related proxy",
            "• algal activity proxy",
            "• spectral anomalies",
            "",
            "These indicators can flag conditions for further investigation, but they do not prove toxicity.",
        ]
        if summary.water_quality_label and "ANOMALY" in summary.water_quality_label.upper():
            lines.extend([
                "",
                "⚠️ Optical anomaly detected — further testing recommended.",
            ])
        return "\n".join(lines)

    def _format_bathing_safety_response(self, summary: WaterBodyTelegramSummary) -> str:
        """Section 6: Bathing and swimming safety assessment."""
        lines = [
            f"🏊 {summary.name} — Bathing Safety",
            "",
            f"JalNetra does not currently have certified bathing-water microbiological or chemical test results for {summary.name}.",
            "",
            "Satellite monitoring alone cannot certify that bathing is safe.",
            "",
            "Current optical monitoring:",
            "🟡 Monitoring data available",
            "🧪 Laboratory bathing-safety result: unavailable",
            "",
            "Check local authority advisories and recent laboratory water-quality results before bathing.",
        ]
        if summary.water_quality_label and "ANOMALY" in summary.water_quality_label.upper():
            lines.extend([
                "",
                "⚠️ Recent optical anomaly detected.",
                "",
                "Avoid treating this as a safety certification. Local testing/advisory information is recommended before bathing.",
            ])
        return "\n".join(lines)

    def _format_water_safety_response(self, summary: WaterBodyTelegramSummary) -> str:
        """General water safety assessment covering potability, toxicity, and swimming."""
        lines = [
            f"🛡️ {summary.name} — Water Safety Assessment",
            "",
            "JalNetra monitors surface optical proxies via Sentinel-2 satellite observations and meteorological conditions.",
            "",
            "JalNetra CANNOT certify:",
            "• Drinking water potability",
            "• Pathogen / microbiological safety",
            "• Chemical toxicity",
            "• Bathing-water microbiological safety",
            "",
            "Current status:",
            "🟡 Remote optical monitoring active",
            "🧪 Laboratory safety certification: unavailable",
            "",
            "Official laboratory testing is required to verify biological and chemical safety.",
        ]
        return "\n".join(lines)

    def _format_water_quality_overview(self, summary: WaterBodyTelegramSummary) -> str:
        """Section 7: General water quality overview in simple language."""
        if summary.observation_count == 0:
            return (
                f"💧 {summary.name} — Water Quality Overview\n\n"
                f"No satellite observations have been recorded yet for this water body."
            )

        if not summary.quality_is_remote_sensing_proxy and "Not calculated" in summary.water_quality_simple_text:
            return (
                f"💧 {summary.name} — Water Quality Overview\n\n"
                f"Latest satellite observation:\n{summary.latest_observation_date}\n\n"
                f"Spectral indicators have not yet been calculated for the latest observation."
            )

        lines = [
            f"💧 {summary.name} — Water Quality Overview",
            "",
            f"Latest satellite observation:\n{summary.latest_observation_date}",
            "",
            "JalNetra optical assessment:",
            "🟡 Monitoring indicators available",
            "",
            f"Turbidity/Sediment:\n{summary.water_quality_label or 'Moderate optical signal'}",
            "",
            f"Simple view:\n\"{summary.water_quality_simple_text}\"",
            "",
            "These are satellite-derived indicators, not laboratory water-quality measurements.",
        ]
        return "\n".join(lines)

    def _format_weather_interpretation(self, weather: Any) -> str:
        """Section 9: Translates forecast into plain-language environmental implications."""
        trend = weather.water_level_trend
        r7d = trend.forecast_rainfall_7d_mm
        max_day = max((f.precipitation_mm for f in weather.forecast), default=0.0)
        dry_days = sum(1 for f in weather.forecast if f.precipitation_mm < 0.5)

        if r7d < 3.0 and dry_days >= 4:
            return (
                "☀️ Mostly dry conditions are expected over the next several days.\n\n"
                "Rainfall forecast is low, so there is currently no strong weather signal "
                "for a rainfall-driven increase in water extent.\n\n"
                "If dry conditions persist, water extent may gradually decline."
            )
        elif r7d >= 50.0 or max_day >= 25.0:
            return (
                "🌧 Significant rainfall is forecast.\n\n"
                "The lake/reservoir may experience increased inflow and potential expansion "
                "of apparent water extent.\n\n"
                "This is a weather-based inference, not a measured water-level forecast."
            )
        elif r7d >= 15.0:
            return (
                "🌧 Rainfall is expected over the coming days.\n\n"
                "This may increase inflow and could contribute to an increase in apparent water extent.\n\n"
                "Current confidence: Moderate."
            )
        else:
            return (
                "🌦 Variable weather is expected.\n\n"
                "Some rainfall is forecast, but the overall rainfall signal is not strong enough "
                "for a confident water-level trend."
            )

    def _format_weather_summary(self, weather: Any) -> str:
        """Section 8: Concise weather summary using Open-Meteo data without raw dump."""
        curr = weather.current
        trend = weather.water_level_trend
        r7d = trend.forecast_rainfall_7d_mm

        wettest = max(weather.forecast, key=lambda f: f.precipitation_mm, default=None)
        if wettest and wettest.precipitation_mm > 0:
            try:
                day_name = datetime.strptime(wettest.date, "%Y-%m-%d").strftime("%A")
            except Exception:
                day_name = wettest.date
            wettest_str = f"{day_name} — {wettest.precipitation_mm:.1f} mm"
        else:
            wettest_str = "None (0 mm)"

        today_f = weather.forecast[0] if weather.forecast else None
        today_rain = today_f.precipitation_mm if today_f else curr.rain_mm
        today_prob = today_f.precipitation_probability_max if today_f else 0

        lines = [
            f"🌦 {weather.water_body_name} Weather",
            "",
            "Now:",
            f"☁️ {curr.temperature_c:.0f}°C · {curr.condition}",
            "",
            "Today:",
            f"🌧 {today_rain:.1f} mm rainfall expected",
            f"🌧 {today_prob}% rain probability",
            "",
            "Next 7 days:",
            f"🌧 {r7d:.1f} mm expected rainfall",
            "",
            "Wettest day:",
            f"{wettest_str}",
            "",
            "Overall:",
            self._format_weather_interpretation(weather),
        ]
        return "\n".join(lines)

    def _format_water_level_forecast(self, weather: Any) -> str:
        """Section 10: Rainfall-driven water-level trend."""
        trend = weather.water_level_trend
        raw_baseline = getattr(trend, "satellite_baseline_status", "Unavailable")
        baseline_status = "Available" if str(raw_baseline).lower() in ("available", "true") else "Unavailable"

        lines = [
            f"💧 Water-Level Outlook — {weather.water_body_name}",
            "",
            "Trend:",
            f"{trend.trend_arrow} {trend.trend_label}",
            "",
            "Why:",
            f"{trend.reason}",
            "",
            "7-day rainfall:",
            f"{trend.forecast_rainfall_7d_mm:.1f} mm",
            "",
            "Rainfall impact:",
            f"{trend.rainfall_impact.upper()}",
            "",
            "Recent satellite baseline:",
            f"{baseline_status}",
            "",
            "Confidence:",
            f"{trend.confidence.value}",
            "",
            "Note:",
            "This is an inferred environmental trend based on weather and satellite observations. It is not a direct water-depth measurement.",
        ]
        return "\n".join(lines)

    def _format_today_summary(
        self, summary: WaterBodyTelegramSummary, weather: Optional[Any] = None
    ) -> str:
        """Section 24: 'Today' semantics distinguishing satellite date, weather, and sensor availability."""
        lines = [
            f"💧 {summary.name} — Today's Status",
            "",
            f"JalNetra's latest satellite observation:\n{summary.latest_observation_date} (Cloud cover: {summary.cloud_cover})",
        ]
        if weather:
            curr = weather.current
            trend = weather.water_level_trend
            lines.extend([
                "",
                "Current weather:",
                f"{curr.temperature_c:.0f}°C · {curr.condition}",
                "",
                "Weather outlook:",
                f"{trend.trend_arrow} {trend.trend_label} — {trend.reason}",
            ])
        lines.extend([
            "",
            "Live water-level sensor:",
            "Not available (in situ IoT demonstration prototype)",
        ])
        return "\n".join(lines)

    # ─── Image Delivery ───────────────────────────────────────────────────────

    async def _send_photo_only(
        self,
        chat_id: int,
        service: WaterBodySummaryService,
        wb_id: str,
    ):
        """Specifically handles image requests and uploads verified binary with buttons (Sections 12-20)."""
        wb = service.wb_repo.get_by_id(wb_id)
        wb_name = wb.name if wb else "Water Body"

        # 1. Resolve latest visual observation using ObservationImageResolver
        latest_visual_result = ObservationImageResolver.get_latest_visual_observation(
            wb_id, service.db, data_dir=service.data_dir
        )

        logger.info("Image delivery request for %s (%s). Result: %s", wb_name, wb_id, bool(latest_visual_result))

        if latest_visual_result:
            obs, img_path = latest_visual_result
            logger.info("Water body resolved: %s (%s)", wb_name, wb_id)
            logger.info("Observation resolved: %s (%s)", obs.id, obs.sensing_date)
            logger.info("Candidate image: %s", img_path.name)
            logger.info("File exists: %s", img_path.exists())
            logger.info("File size: %s bytes", img_path.stat().st_size if img_path.exists() else 0)
            logger.info("File readable: %s", img_path.is_file())

            if img_path.exists() and img_path.is_file() and img_path.stat().st_size > 0:
                try:
                    photo_bytes = img_path.read_bytes()
                    obs_date_str = obs.sensing_date.strftime("%d %b %Y")
                    cc = getattr(obs, "cloud_cover_percent", None)
                    if cc is None:
                        cc = getattr(obs, "cloud_cover_percentage", None)
                    cloud_str = f"{cc:.1f}%" if cc is not None else "0.0%"

                    caption = (
                        f"📸 Latest visual observation\n"
                        f"{wb_name}\n"
                        f"{obs_date_str}\n"
                        f"Cloud cover: {cloud_str}"
                    )

                    keyboard = {
                        "inline_keyboard": [
                            [
                                (
                                    {"text": "🗺 Location", "url": f"https://www.google.com/maps/search/?api=1&query={wb.centroid_lat},{wb.centroid_lon}"}
                                    if (wb and wb.centroid_lat and wb.centroid_lon)
                                    else {"text": "🗺 Location", "callback_data": f"wb_loc:{wb_id}"}
                                ),
                                {"text": "💧 Water Quality", "callback_data": f"wb_qual:{wb_id}"},
                                {"text": "🌦 Weather", "callback_data": f"wb_weath:{wb_id}"},
                            ]
                        ]
                    }

                    logger.info("Telegram upload started: chat_id=%s, size=%s", chat_id, len(photo_bytes))
                    upload_success = await self.client.send_photo(
                        chat_id=chat_id,
                        photo_bytes=photo_bytes,
                        filename=img_path.name,
                        caption=caption,
                        reply_markup=keyboard,
                    )
                    logger.info("Telegram upload result: %s", "SUCCESS" if upload_success else "FAILED")
                    if upload_success:
                        return
                    logger.warning("Telegram sendPhoto API call failed for %s", wb_id)
                except Exception as exc:
                    logger.warning("Error reading/uploading photo for %s: %s", wb_id, exc)

        # Fallback message
        obs_list = service.obs_repo.list_for_water_body(wb_id)
        if obs_list:
            fallback = (
                f"📸 Latest Visual — {wb_name}\n\n"
                f"Observation records exist ({len(obs_list)} total), but no readable visual image is currently stored on disk.\n"
                f"Use the JalNetra application to fetch visual observations first."
            )
        else:
            fallback = (
                f"📸 Latest Visual — {wb_name}\n\n"
                f"No visual observations have been fetched yet for this water body.\n"
                f"Use the JalNetra application to fetch Sentinel-2 observations first."
            )
        await self.client.send_message(chat_id, fallback)

    async def _send_water_body_summary_and_photo(
        self,
        chat_id: int,
        service: WaterBodySummaryService,
        wb_id: str,
        is_today: bool = False,
    ):
        """Sends structured summary card with inline buttons and uploads latest photo if present."""
        summary = service.get_water_body_summary(wb_id)
        if is_today:
            msg_text = self._format_today_summary(summary)
        else:
            msg_text = service.format_telegram_summary_message(summary)

        keyboard = self._build_water_body_inline_keyboard(wb_id, summary.google_maps_url)
        await self.client.send_message(chat_id, msg_text, reply_markup=keyboard)

        # Upload photo directly if valid local image exists
        if summary.has_stored_visual_image and summary.latest_image_path:
            p = Path(summary.latest_image_path)
            if p.exists() and p.is_file() and p.stat().st_size > 0:
                try:
                    photo_bytes = p.read_bytes()
                    caption = (
                        f"📸 Latest visual observation\n"
                        f"{summary.name}\n"
                        f"{summary.latest_observation_date}\n"
                        f"Cloud cover: {summary.cloud_cover}"
                    )
                    await self.client.send_photo(
                        chat_id=chat_id,
                        photo_bytes=photo_bytes,
                        filename=p.name,
                        caption=caption,
                    )
                except Exception as exc:
                    logger.warning("Failed to send latest visual observation photo: %s", exc)

    async def _send_weather_summary(self, chat_id: int, db: Session, wb_id: str):
        """Fetches and formats real-time Open-Meteo weather for Telegram."""
        from app.services.weather import WeatherService, MissingCoordinatesError
        weather_svc = WeatherService(db)
        try:
            weather = await weather_svc.get_weather_for_water_body(wb_id)
            text_out = self._format_weather_summary(weather)
            keyboard = self._build_water_body_inline_keyboard(wb_id)
            await self.client.send_message(chat_id, text_out, reply_markup=keyboard)
        except MissingCoordinatesError:
            await self.client.send_message(
                chat_id,
                "⚠️ Weather unavailable: This water body does not have valid coordinates.",
            )
        except Exception as exc:
            logger.warning("Weather fetch error for %s: %s", wb_id, exc)
            await self.client.send_message(
                chat_id,
                "⚠️ Weather data is temporarily unavailable from Open-Meteo.",
            )

    async def _send_water_level_forecast(self, chat_id: int, db: Session, wb_id: str):
        """Fetches and formats rainfall-driven water level trend for Telegram."""
        from app.services.weather import WeatherService, MissingCoordinatesError
        weather_svc = WeatherService(db)
        try:
            weather = await weather_svc.get_weather_for_water_body(wb_id)
            text_out = self._format_water_level_forecast(weather)
            keyboard = self._build_water_body_inline_keyboard(wb_id)
            await self.client.send_message(chat_id, text_out, reply_markup=keyboard)
        except MissingCoordinatesError:
            await self.client.send_message(
                chat_id,
                "⚠️ Water-level trend unavailable: This water body does not have valid coordinates.",
            )
        except Exception as exc:
            logger.warning("Water-level trend fetch error for %s: %s", wb_id, exc)
            await self.client.send_message(
                chat_id,
                "⚠️ Water-level trend data is temporarily unavailable.",
            )

    # ─── Interactive Callback Handler ─────────────────────────────────────────

    async def handle_callback_query(self, query: TelegramCallbackQuery):
        """Handles interactive inline button clicks."""
        chat_id = query.message.chat.id if query.message else (query.from_user.id if query.from_user else 0)
        data = query.data or ""
        logger.info("Handling callback query from chat %s: %s", chat_id, data)

        await self.client.answer_callback_query(query.id)

        if ":" not in data:
            return

        action, wb_id = data.split(":", 1)
        wb_id = wb_id.strip()

        with self._get_db() as db:
            service = self.summary_service or WaterBodySummaryService(db)
            try:
                summary = service.get_water_body_summary(wb_id)
            except Exception:
                await self.client.send_message(chat_id, "❌ Water body details not found.")
                return

            if action == "wb_img":
                await self._send_photo_only(chat_id, service, wb_id)

            elif action == "wb_qual":
                msg = self._format_water_quality_overview(summary)
                keyboard = self._build_water_body_inline_keyboard(wb_id, summary.google_maps_url)
                await self.client.send_message(chat_id, msg, reply_markup=keyboard)

            elif action == "wb_mon":
                lines = [
                    f"📊 Monitoring History — {summary.name}",
                    "",
                    f"Total Observations: {summary.observation_count}",
                ]
                if summary.monitoring_start and summary.monitoring_end:
                    lines.append(f"Period: {summary.monitoring_start} → {summary.monitoring_end}")
                lines.append(f"Frequency: {summary.observation_frequency}")
                lines.append(f"Latest Sensing: {summary.latest_observation_date}")
                lines.append(f"Cloud Cover: {summary.cloud_cover}")
                lines.append(f"Apparent Water Extent: {summary.apparent_water_extent}")
                keyboard = self._build_water_body_inline_keyboard(wb_id, summary.google_maps_url)
                await self.client.send_message(chat_id, "\n".join(lines), reply_markup=keyboard)

            elif action == "wb_weath":
                await self._send_weather_summary(chat_id, db, wb_id)

            elif action == "wb_loc":
                lines = [f"📍 {summary.name}", "", summary.location]
                if summary.google_maps_url:
                    lines.extend(["", "🗺 Open in Google Maps", summary.google_maps_url])
                keyboard = self._build_water_body_inline_keyboard(wb_id, summary.google_maps_url)
                await self.client.send_message(chat_id, "\n".join(lines), reply_markup=keyboard)

    # ─── Message Dispatcher ───────────────────────────────────────────────────

    async def handle_message(self, message: TelegramMessage):
        """Processes incoming user text message (both slash commands and natural language)."""
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

        # 1. Check for slash commands (Preserve 100% backward compatibility)
        if raw_text.startswith("/"):
            parts = raw_text.split(maxsplit=1)
            command = parts[0].lower()
            if "@" in command:
                command = command.split("@")[0]
            args = parts[1].strip() if len(parts) > 1 else ""

            logger.info("Processing Telegram slash command from chat %s: '%s'", chat_id, command)

            if command == "/start":
                await self.client.send_message(chat_id, START_MESSAGE)
                return

            if command == "/help":
                await self.client.send_message(chat_id, HELP_MESSAGE)
                return

            if command == "/ping":
                await self.client.send_message(chat_id, PING_MESSAGE)
                return

            if command == "/status":
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
                return

            if command == "/list":
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
                    return

            if command == "/waterbody":
                if not args:
                    await self.client.send_message(
                        chat_id,
                        "Please specify a water body name.\nExample: /waterbody Phewa Tal\n\nUse /list to see all available water bodies.",
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
                    self.intent_service.set_chat_context(chat_id, target_wb.id)
                    await self._send_water_body_summary_and_photo(chat_id, service, target_wb.id)
                    return

            if command == "/ai":
                if not args:
                    await self.client.send_message(
                        chat_id,
                        "Please provide a question after /ai.\nExample: /ai What is JalNetra?",
                    )
                    return

                # Read-only guard
                forbidden_keywords = [
                    "fetch satellite", "delete database", "run processing",
                    "execute command", "rm ", "drop table",
                ]
                if any(kw in args.lower() for kw in forbidden_keywords):
                    await self.client.send_message(
                        chat_id,
                        "⚠️ JalNetra AI is read-only in this version and cannot execute administrative server actions.",
                    )
                    return

                with self._get_db() as db:
                    service = self.summary_service or WaterBodySummaryService(db)
                    all_wbs = service.list_water_bodies()
                    matched_wb = None
                    for wb in all_wbs:
                        if wb.name.lower() in args.lower() or (wb.normalized_name and wb.normalized_name.lower() in args.lower()):
                            matched_wb = wb
                            break

                    if matched_wb:
                        self.intent_service.set_chat_context(chat_id, matched_wb.id)
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
                return

        # 2. Natural Language Processing (Primary interaction mode)
        logger.info("Processing natural language query from chat %s: '%s'", chat_id, raw_text)

        with self._get_db() as db:
            service = self.summary_service or WaterBodySummaryService(db)
            all_wbs = service.list_water_bodies()

            intent_result: IntentResult = self.intent_service.classify_intent(
                text=raw_text,
                chat_id=chat_id,
                all_wbs=all_wbs,
            )

            intent = intent_result.intent
            secondary_intent = intent_result.secondary_intent
            target_wb = intent_result.water_body

            # Disambiguation needed
            if intent_result.water_body_candidates and len(intent_result.water_body_candidates) > 1:
                lines = [f'I found multiple possible water bodies:\n']
                for idx, wb in enumerate(intent_result.water_body_candidates, start=1):
                    lines.append(f"{idx}. {wb.name}")
                lines.append("\nWhich one would you like?")
                await self.client.send_message(chat_id, "\n".join(lines))
                return

            if intent == TelegramIntent.LIST_WATER_BODIES:
                if not all_wbs:
                    await self.client.send_message(
                        chat_id,
                        "🌊 No water bodies are currently available in JalNetra.\n"
                        "Add a water body from the JalNetra application first.",
                    )
                    return
                lines = ["🌊 Registered Water Bodies\n"]
                for idx, wb in enumerate(all_wbs, start=1):
                    lines.append(f"{idx}. {wb.name}")
                lines.append("\nAsk me about any water body, or type /waterbody <name>.")
                await self.client.send_message(chat_id, "\n".join(lines))
                return

            if intent == TelegramIntent.HELP:
                await self.client.send_message(chat_id, HELP_MESSAGE)
                return

            if intent == TelegramIntent.STATUS:
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
                return

            # Intents requiring a water body:
            water_body_required_intents = (
                TelegramIntent.WATER_BODY_INFO,
                TelegramIntent.LATEST_IMAGE,
                TelegramIntent.LOCATION,
                TelegramIntent.WATER_QUALITY,
                TelegramIntent.WATER_EXTENT,
                TelegramIntent.MONITORING_FREQUENCY,
                TelegramIntent.WATER_VOLUME,
                TelegramIntent.WEATHER,
                TelegramIntent.RAIN_FORECAST,
                TelegramIntent.WATER_LEVEL_FORECAST,
                TelegramIntent.DRINKABILITY,
                TelegramIntent.TOXICITY,
                TelegramIntent.BATHING_SAFETY,
                TelegramIntent.WATER_SAFETY,
            )

            if intent in water_body_required_intents:
                if target_wb is None:
                    await self.client.send_message(
                        chat_id,
                        "Please specify which water body you'd like to check.\n"
                        "Example: \"Is the water at Phewa Tal drinkable?\" or \"Give me the latest image of Phewa Tal\".\n\n"
                        "Type /list to see all registered water bodies.",
                    )
                    return

                # Route to image delivery
                if intent == TelegramIntent.LATEST_IMAGE:
                    await self._send_photo_only(chat_id, service, target_wb.id)
                    return

                summary = service.get_water_body_summary(target_wb.id)
                keyboard = self._build_water_body_inline_keyboard(target_wb.id, summary.google_maps_url)

                # Compound / Multi-Intent handling (Section 23)
                if secondary_intent:
                    from app.services.weather import WeatherService
                    weather_svc = WeatherService(db)
                    try:
                        weather = await weather_svc.get_weather_for_water_body(target_wb.id)
                    except Exception:
                        weather = None

                    if intent == TelegramIntent.DRINKABILITY and secondary_intent == TelegramIntent.WATER_LEVEL_FORECAST:
                        part1 = self._format_drinkability_response(summary)
                        part2 = self._format_water_level_forecast(weather) if weather else "Water-level forecast is temporarily unavailable."
                        combined = f"{part1}\n\n{'─' * 28}\n\n{part2}"
                        await self.client.send_message(chat_id, combined, reply_markup=keyboard)
                        return

                    if intent == TelegramIntent.WATER_QUALITY and secondary_intent in (TelegramIntent.WEATHER, TelegramIntent.RAIN_FORECAST):
                        part1 = self._format_water_quality_overview(summary)
                        part2 = self._format_weather_summary(weather) if weather else "Weather forecast is temporarily unavailable."
                        combined = f"{part1}\n\n{'─' * 28}\n\n{part2}"
                        await self.client.send_message(chat_id, combined, reply_markup=keyboard)
                        return

                    if intent in (TelegramIntent.WEATHER, TelegramIntent.RAIN_FORECAST) and secondary_intent == TelegramIntent.WATER_LEVEL_FORECAST:
                        if weather:
                            part1 = self._format_weather_summary(weather)
                            part2 = self._format_water_level_forecast(weather)
                            combined = f"{part1}\n\n{'─' * 28}\n\n{part2}"
                            await self.client.send_message(chat_id, combined, reply_markup=keyboard)
                            return

                # Single Intent Routing
                if intent == TelegramIntent.DRINKABILITY:
                    msg = self._format_drinkability_response(summary)
                    await self.client.send_message(chat_id, msg, reply_markup=keyboard)
                    return

                if intent == TelegramIntent.TOXICITY:
                    msg = self._format_toxicity_response(summary)
                    await self.client.send_message(chat_id, msg, reply_markup=keyboard)
                    return

                if intent == TelegramIntent.BATHING_SAFETY:
                    msg = self._format_bathing_safety_response(summary)
                    await self.client.send_message(chat_id, msg, reply_markup=keyboard)
                    return

                if intent == TelegramIntent.WATER_SAFETY:
                    msg = self._format_water_safety_response(summary)
                    await self.client.send_message(chat_id, msg, reply_markup=keyboard)
                    return

                if intent == TelegramIntent.WATER_LEVEL_FORECAST:
                    await self._send_water_level_forecast(chat_id, db, target_wb.id)
                    return

                if intent in (TelegramIntent.WEATHER, TelegramIntent.RAIN_FORECAST):
                    await self._send_weather_summary(chat_id, db, target_wb.id)
                    return

                if intent == TelegramIntent.LOCATION:
                    lines = [
                        f"📍 {summary.name}",
                        "",
                        summary.location,
                    ]
                    if summary.google_maps_url:
                        lines.extend([
                            "",
                            "🗺 Open in Google Maps",
                            summary.google_maps_url,
                        ])
                    await self.client.send_message(chat_id, "\n".join(lines), reply_markup=keyboard)
                    return

                if intent == TelegramIntent.WATER_QUALITY:
                    msg = self._format_water_quality_overview(summary)
                    await self.client.send_message(chat_id, msg, reply_markup=keyboard)
                    return

                if intent == TelegramIntent.WATER_EXTENT:
                    lines = [
                        f"📐 Water Extent & Surface Area — {summary.name}",
                        "",
                        f"Surface Area: {summary.surface_area_text}",
                        f"Latest Apparent Extent: {summary.apparent_water_extent}",
                        f"Latest Observation: {summary.latest_observation_date}",
                    ]
                    await self.client.send_message(chat_id, "\n".join(lines), reply_markup=keyboard)
                    return

                if intent == TelegramIntent.MONITORING_FREQUENCY:
                    lines = [
                        f"🔄 Change & Monitoring Frequency — {summary.name}",
                        "",
                        f"Observed across {summary.observation_count} observation{'s' if summary.observation_count != 1 else ''}",
                    ]
                    if summary.monitoring_start and summary.monitoring_end:
                        lines.append(f"Period: {summary.monitoring_start} → {summary.monitoring_end}")
                    lines.append(f"Frequency: {summary.observation_frequency}")
                    lines.append(f"Latest Observation: {summary.latest_observation_date}")
                    await self.client.send_message(chat_id, "\n".join(lines), reply_markup=keyboard)
                    return

                if intent == TelegramIntent.WATER_VOLUME:
                    lines = [
                        f"💧 Estimated Water Volume — {summary.name}",
                        "",
                        summary.water_volume,
                    ]
                    if summary.water_volume_note:
                        lines.extend(["", summary.water_volume_note])
                    await self.client.send_message(chat_id, "\n".join(lines), reply_markup=keyboard)
                    return

                # WATER_BODY_INFO: send full summary card + photo
                await self._send_water_body_summary_and_photo(
                    chat_id, service, target_wb.id, is_today=intent_result.is_today_query
                )
                return

            if intent == TelegramIntent.AI_QUESTION:
                if target_wb:
                    ai_svc = self.ai_service
                    if getattr(ai_svc, "db", None) is None:
                        ai_svc.db = db
                    try:
                        res = ai_svc.generate_analysis_response(
                            water_body_id=target_wb.id,
                            observation_id=None,
                            question=raw_text,
                        )
                        reply = f"🤖 JalNetra AI — {target_wb.name}\n\n{res.answer}"
                    except Exception as exc:
                        logger.warning("AI water body analysis error: %s", exc)
                        reply = f"🤖 JalNetra AI\n\n{self.ai_service.generate_general_response(raw_text)}"
                else:
                    reply = f"🤖 JalNetra AI\n\n{self.ai_service.generate_general_response(raw_text)}"

                await self.client.send_message(chat_id, reply)
                return

            # UNKNOWN intent fallback
            await self.client.send_message(
                chat_id,
                "I couldn't quite understand that. You can ask me naturally, such as:\n"
                "• \"Is the water at Phewa Tal drinkable?\"\n"
                "• \"Can I bathe here?\"\n"
                "• \"Will the water level increase?\"\n"
                "• \"Will it rain tomorrow?\"\n"
                "• \"Latest image of Phewa Tal\"\n"
                "• \"Where is Phewa Tal?\"\n"
                "• \"List all water bodies\"\n\n"
                "Or type /help for command options.",
            )
