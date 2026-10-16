import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.repositories.water_body_repository import WaterBodyRepository
from app.db.repositories.satellite_observation_repository import SatelliteObservationRepository
from app.services.spectral import SpectralAnalysisService
from app.services.ai.client import OpenAIClientWrapper, AIServiceError
from app.services.ai.models import AIStatusResponse, AIAnalysisResponse
from app.services.ai.prompts import JALNETRA_SYSTEM_PROMPT, GENERAL_QUESTION_PROMPT

logger = logging.getLogger("jalnetra.services.ai")


class AIService:
    """
    Dedicated JalNetra AI Assistant Service.
    Provides read-only observational explanations of satellite imagery and
    remote-sensing spectral indicators.
    """

    def __init__(self, db: Optional[Session] = None, client: Optional[OpenAIClientWrapper] = None):
        self.db = db
        self.client = client or OpenAIClientWrapper()

    def get_status(self) -> AIStatusResponse:
        enabled = settings.AI_ENABLED
        key_configured = bool(settings.OPENAI_API_KEY.strip())
        return AIStatusResponse(
            enabled=enabled,
            configured=key_configured and enabled,
            model=settings.OPENAI_MODEL,
            provider="openai",
        )

    def build_water_body_context(
        self, water_body_id: str, observation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Builds a compact, structured representation of the water body and
        its observations/spectral indicators directly from the database and cached analyses.
        Never loads or transmits large rasters or raw imagery.
        """
        if not self.db:
            raise AIServiceError(
                message="Database session required to build water body analysis context.",
                code="DB_SESSION_REQUIRED",
                status_code=500,
            )

        wb_repo = WaterBodyRepository(self.db)
        obs_repo = SatelliteObservationRepository(self.db)

        wb = wb_repo.get_by_id(water_body_id)
        if not wb:
            raise AIServiceError(
                message=f"Water body with ID '{water_body_id}' not found.",
                code="WATER_BODY_NOT_FOUND",
                status_code=404,
            )

        # Build location description
        location_parts = [p for p in [wb.city, wb.district, wb.state_province, wb.country] if p]
        location_str = ", ".join(location_parts) if location_parts else "Location unspecified"

        context: Dict[str, Any] = {
            "water_body": {
                "name": wb.name,
                "type": wb.water_body_type or "unspecified",
                "area_km2": round(wb.area_sq_km, 3) if wb.area_sq_km else None,
                "location": location_str,
            }
        }

        # Chronological observations timeline
        all_obs = obs_repo.list_for_water_body(water_body_id)
        timeline = []
        for o in all_obs:
            cc = getattr(o, "cloud_cover_percent", None)
            if cc is None:
                cc = getattr(o, "cloud_cover_percentage", 0.0)
            area = getattr(o, "derived_water_area_sq_km", None)
            if area is None:
                area = getattr(o, "apparent_water_extent_sq_km", None)
            qs = getattr(o, "quality_score", None)

            timeline.append({
                "observation_id": o.id,
                "date": o.sensing_date.strftime("%Y-%m-%d") if o.sensing_date else "unknown",
                "cloud_cover_percent": round(cc, 1) if cc is not None else 0.0,
                "apparent_extent_km2": round(area, 3) if area is not None else None,
                "quality_score": round(qs, 1) if qs is not None else None,
            })
        context["temporal_timeline"] = timeline

        # Selected observation details
        target_obs = None
        if observation_id:
            target_obs = obs_repo.get_by_id(observation_id)
        elif all_obs:
            target_obs = all_obs[-1]  # Latest by default

        if target_obs:
            target_cc = getattr(target_obs, "cloud_cover_percent", None)
            if target_cc is None:
                target_cc = getattr(target_obs, "cloud_cover_percentage", 0.0)
            target_area = getattr(target_obs, "derived_water_area_sq_km", None)
            if target_area is None:
                target_area = getattr(target_obs, "apparent_water_extent_sq_km", None)

            context["selected_observation"] = {
                "observation_id": target_obs.id,
                "date": target_obs.sensing_date.strftime("%Y-%m-%d") if target_obs.sensing_date else "unknown",
                "cloud_cover_percent": round(target_cc, 1) if target_cc is not None else 0.0,
                "apparent_extent_km2": round(target_area, 3) if target_area is not None else None,
                "apparent_extent_status": "estimated_satellite_derived" if target_area is not None else "unmeasured",
            }

            # Gather spectral indicators if available
            try:
                spectral_svc = SpectralAnalysisService(self.db)
                summary = spectral_svc.get_multi_indicator_summary(water_body_id, target_obs.id)
                indicators_data = []
                for ind in summary.indicators:
                    indicators_data.append({
                        "indicator": ind.indicator,
                        "label": ind.indicator_label,
                        "value": round(ind.value, 4) if ind.value is not None else None,
                        "classification": ind.classification,
                        "quality": ind.quality,
                        "valid_pixel_percent": round(ind.valid_pixel_percent, 1),
                        "disclaimer": "Uncalibrated remote-sensing proxy, NOT laboratory NTU or mg/m³",
                    })
                context["spectral_indicators"] = indicators_data
            except Exception as e:
                logger.debug("Could not attach spectral summary to AI context: %s", e)
                context["spectral_indicators"] = []

        # Attach meteorological and water-level trend context
        try:
            from app.services.weather import WeatherService
            weather_svc = WeatherService(self.db)
            weather_resp = weather_svc.get_weather_for_water_body_sync(water_body_id)
            if weather_resp:
                context["weather"] = {
                    "provider": weather_resp.provider,
                    "current": {
                        "temperature_c": weather_resp.current.temperature_c,
                        "apparent_temperature_c": weather_resp.current.apparent_temperature_c,
                        "humidity_percent": weather_resp.current.humidity_percent,
                        "precipitation_mm": weather_resp.current.precipitation_mm,
                        "cloud_cover_percent": weather_resp.current.cloud_cover_percent,
                        "wind_speed_kmh": weather_resp.current.wind_speed_kmh,
                        "condition": weather_resp.current.condition,
                    },
                    "water_level_trend": {
                        "trend": weather_resp.water_level_trend.trend.value,
                        "trend_label": weather_resp.water_level_trend.trend_label,
                        "confidence": weather_resp.water_level_trend.confidence.value,
                        "rainfall_impact": weather_resp.water_level_trend.rainfall_impact.value,
                        "dryness_impact": weather_resp.water_level_trend.dryness_impact.value,
                        "forecast_rainfall_7d_mm": weather_resp.water_level_trend.forecast_rainfall_7d_mm,
                        "rain_probability_label": weather_resp.water_level_trend.rain_probability_label,
                        "reason": weather_resp.water_level_trend.reason,
                        "expected_response": weather_resp.water_level_trend.expected_response,
                        "satellite_baseline_status": weather_resp.water_level_trend.satellite_baseline_status,
                        "disclaimer": weather_resp.water_level_trend.disclaimer,
                    },
                }
            else:
                context["weather"] = {"status": "unavailable"}
        except Exception as e:
            logger.debug("Could not attach weather summary to AI context: %s", e)
            context["weather"] = {"status": "unavailable"}

        return context

    def generate_analysis_response(
        self,
        water_body_id: Optional[str],
        observation_id: Optional[str],
        question: str,
    ) -> AIAnalysisResponse:
        """
        Generates an AI response for an analysis question, injecting structured context
        for the specified water body and observation.
        """
        status = self.get_status()
        if not status.enabled:
            raise AIServiceError(
                message="AI service is disabled in system configuration.",
                code="AI_DISABLED",
                status_code=503,
            )
        if not status.configured:
            raise AIServiceError(
                message="AI service is not configured. Missing OpenAI API key.",
                code="AI_NOT_CONFIGURED",
                status_code=503,
            )

        messages = [
            {"role": "system", "content": JALNETRA_SYSTEM_PROMPT}
        ]

        water_body_name = None
        obs_date = None

        if water_body_id:
            context = self.build_water_body_context(water_body_id, observation_id)
            water_body_name = context.get("water_body", {}).get("name")
            obs_date = context.get("selected_observation", {}).get("date")

            context_str = json.dumps(context, indent=2)
            user_content = (
                f"=== JALNETRA OBSERVATION DATA (JSON) ===\n"
                f"{context_str}\n\n"
                f"=== USER QUESTION ===\n"
                f"{question}"
            )
        else:
            user_content = question

        messages.append({"role": "user", "content": user_content})

        answer = self.client.generate_chat_completion(
            messages=messages,
            model=settings.OPENAI_MODEL,
            max_tokens=settings.AI_MAX_OUTPUT_TOKENS,
        )

        return AIAnalysisResponse(
            answer=answer,
            water_body_name=water_body_name,
            observation_date=obs_date,
            model=settings.OPENAI_MODEL,
        )

    def generate_general_response(self, question: str) -> str:
        """
        Generates a general informational response for Telegram /ai command or general queries.
        Strictly informative and read-only.
        """
        status = self.get_status()
        if not status.enabled:
            return "⚠️ JalNetra AI is currently disabled in system configuration."
        if not status.configured:
            return "⚠️ JalNetra AI is not configured. An OpenAI API key has not been provided."

        messages = [
            {"role": "system", "content": GENERAL_QUESTION_PROMPT},
            {"role": "user", "content": question},
        ]

        try:
            return self.client.generate_chat_completion(
                messages=messages,
                model=settings.OPENAI_MODEL,
                max_tokens=settings.AI_MAX_OUTPUT_TOKENS,
            )
        except AIServiceError as e:
            return f"⚠️ {e.message}"
        except Exception as e:
            logger.error("Error generating general AI response: %s", e)
            return "⚠️ An error occurred while communicating with JalNetra AI."
