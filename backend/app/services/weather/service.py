import logging
from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.repositories.water_body_repository import WaterBodyRepository
from app.db.models.satellite_observation import SatelliteObservation
from app.services.water_body_service import WaterBodyNotFoundError
from app.services.weather.models import (
    WeatherResponse,
    DailyForecastItem,
    WeatherImpactResponse,
    WeatherStatusResponse,
    LocationInfo,
)
from app.services.weather.client import (
    OpenMeteoClient,
    WeatherClientError,
    WeatherTimeoutError,
    WeatherRateLimitError,
)
from app.services.weather.cache import weather_cache, WeatherCache
from app.services.weather.interpretation import WaterLevelTrendEngine

logger = logging.getLogger("jalnetra.weather.service")


class MissingCoordinatesError(Exception):
    """Raised when a water body does not have valid centroid coordinates."""
    pass


class WeatherService:
    """
    Main Weather Service for JalNetra 2.0.
    Integrates Open-Meteo forecasts, cache management, water-body geospatial centroids,
    and environmental satellite-correlation trend calculations.
    """

    def __init__(
        self,
        db: Session,
        client: Optional[OpenMeteoClient] = None,
        cache: Optional[WeatherCache] = None,
    ):
        self.db = db
        self.client = client or OpenMeteoClient()
        self.cache = cache or weather_cache
        self.wb_repo = WaterBodyRepository(db)

    def get_status(self) -> WeatherStatusResponse:
        """Returns weather service operational and configuration status."""
        return WeatherStatusResponse(
            enabled=True,
            provider="Open-Meteo",
            configured=True,
            requires_api_key=False,
            details="Open-Meteo Weather Forecast API active (no API key required).",
        )

    def _get_recent_apparent_extents(self, water_body_id: str) -> List[Tuple[str, float]]:
        """
        Retrieves recent chronological observations to evaluate apparent extent baseline.
        Returns list of (sensing_date_iso, extent_sq_km).
        """
        stmt = (
            select(SatelliteObservation)
            .where(SatelliteObservation.water_body_id == water_body_id)
            .order_by(SatelliteObservation.sensing_date.asc())
        )
        observations = self.db.execute(stmt).scalars().all()

        results = []
        for obs in observations:
            extent = getattr(obs, "derived_water_area_sq_km", None)
            if extent is None:
                extent = getattr(obs, "apparent_water_extent_sq_km", None)
            if extent is not None and extent > 0 and obs.sensing_date:
                results.append((obs.sensing_date.strftime("%Y-%m-%d"), float(extent)))

        return results

    async def get_weather_for_water_body(
        self,
        water_body_id: str,
        force_refresh: bool = False,
    ) -> WeatherResponse:
        """
        Retrieves comprehensive weather, 7-day forecast, and qualitative water-level trend.
        Uses cached data if fresh, with graceful fallback to stale cache on upstream failure.
        """
        wb = self.wb_repo.get_by_id(water_body_id)
        if not wb:
            raise WaterBodyNotFoundError(f"Water body with ID '{water_body_id}' not found.")

        if wb.centroid_lat is None or wb.centroid_lon is None:
            raise MissingCoordinatesError(
                f"Water body '{wb.name}' does not have valid centroid coordinates (lat/lon) for weather forecasting."
            )

        lat = float(wb.centroid_lat)
        lon = float(wb.centroid_lon)

        # 1. Check Cache
        if not force_refresh:
            cached_dict = self.cache.get("wb_weather", water_body_id)
            if cached_dict:
                try:
                    return WeatherResponse.model_validate(cached_dict)
                except Exception as exc:
                    logger.debug("Failed validating cached weather model: %s", exc)

        # 2. Call Open-Meteo
        try:
            raw_data = await self.client.fetch_forecast(latitude=lat, longitude=lon, forecast_days=7)
        except (WeatherClientError, WeatherTimeoutError, WeatherRateLimitError) as exc:
            # Check for stale cache fallback
            stale_dict = self.cache.get("wb_weather", water_body_id, allow_stale=True)
            if stale_dict:
                logger.warning("Serving stale cached weather for %s due to upstream error: %s", water_body_id, exc)
                return WeatherResponse.model_validate(stale_dict)
            raise

        # 3. Parse Weather & Forecast
        current_weather = self.client.parse_current_weather(raw_data)
        daily_forecast = self.client.parse_daily_forecast(raw_data)

        # 4. Integrate Satellite Extent Baseline & Compute Trend
        recent_extents = self._get_recent_apparent_extents(water_body_id)
        trend = WaterLevelTrendEngine.calculate_trend(
            forecast=daily_forecast,
            recent_apparent_extents=recent_extents,
        )

        timezone_str = raw_data.get("timezone", "auto")

        response = WeatherResponse(
            water_body_id=wb.id,
            water_body_name=wb.name,
            location=LocationInfo(
                latitude=round(lat, 4),
                longitude=round(lon, 4),
                timezone=timezone_str,
            ),
            provider="Open-Meteo",
            current=current_weather,
            forecast=daily_forecast,
            water_level_trend=trend,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

        # 5. Store in Cache
        self.cache.set("wb_weather", water_body_id, response.model_dump(), is_forecast=True)

        return response

    async def get_forecast_for_water_body(
        self,
        water_body_id: str,
    ) -> List[DailyForecastItem]:
        """Returns 7-day daily forecast only."""
        full_weather = await self.get_weather_for_water_body(water_body_id)
        return full_weather.forecast

    async def get_weather_impact(
        self,
        water_body_id: str,
    ) -> WeatherImpactResponse:
        """Returns qualitative rainfall-driven water-level trend and impact summary."""
        full_weather = await self.get_weather_for_water_body(water_body_id)
        return WeatherImpactResponse(
            water_body_id=full_weather.water_body_id,
            water_body_name=full_weather.water_body_name,
            provider=full_weather.provider,
            water_level_trend=full_weather.water_level_trend,
            fetched_at=full_weather.fetched_at,
        )

    def get_weather_for_water_body_sync(
        self,
        water_body_id: str,
        force_refresh: bool = False,
    ) -> Optional[WeatherResponse]:
        """Synchronous version of get_weather_for_water_body, ideal for synchronous AI context generation."""
        wb = self.wb_repo.get_by_id(water_body_id)
        if not wb or wb.centroid_lat is None or wb.centroid_lon is None:
            return None

        lat = float(wb.centroid_lat)
        lon = float(wb.centroid_lon)

        if not force_refresh:
            cached_dict = self.cache.get("wb_weather", water_body_id)
            if cached_dict:
                try:
                    return WeatherResponse.model_validate(cached_dict)
                except Exception:
                    pass

        try:
            raw_data = self.client.fetch_forecast_sync(latitude=lat, longitude=lon, forecast_days=7)
        except Exception as exc:
            stale_dict = self.cache.get("wb_weather", water_body_id, allow_stale=True)
            if stale_dict:
                return WeatherResponse.model_validate(stale_dict)
            logger.warning("Sync weather fetch failed for %s: %s", water_body_id, exc)
            return None

        current_weather = self.client.parse_current_weather(raw_data)
        daily_forecast = self.client.parse_daily_forecast(raw_data)
        recent_extents = self._get_recent_apparent_extents(water_body_id)
        trend = WaterLevelTrendEngine.calculate_trend(
            forecast=daily_forecast,
            recent_apparent_extents=recent_extents,
        )

        response = WeatherResponse(
            water_body_id=wb.id,
            water_body_name=wb.name,
            location=LocationInfo(
                latitude=round(lat, 4),
                longitude=round(lon, 4),
                timezone=raw_data.get("timezone", "auto"),
            ),
            provider="Open-Meteo",
            current=current_weather,
            forecast=daily_forecast,
            water_level_trend=trend,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

        self.cache.set("wb_weather", water_body_id, response.model_dump(), is_forecast=True)
        return response
