import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.water_body_service import WaterBodyNotFoundError
from app.services.weather import (
    WeatherService,
    WeatherResponse,
    DailyForecastItem,
    WeatherImpactResponse,
    WeatherStatusResponse,
    MissingCoordinatesError,
    WeatherTimeoutError,
    WeatherRateLimitError,
    WeatherClientError,
)

logger = logging.getLogger("jalnetra.api.weather")

router = APIRouter(prefix="/weather", tags=["Weather"])


def get_weather_service(db: Session = Depends(get_db)) -> WeatherService:
    return WeatherService(db)


@router.get(
    "/status",
    response_model=WeatherStatusResponse,
    summary="Check weather service status and configuration",
)
async def get_weather_status(
    weather_service: WeatherService = Depends(get_weather_service),
):
    """
    Returns the operational and provider status of the Weather integration (Open-Meteo).
    Does not require authentication or API keys.
    """
    return weather_service.get_status()


@router.get(
    "/water-bodies/{water_body_id}",
    response_model=WeatherResponse,
    summary="Get current weather, 7-day forecast, and rainfall water-level trend for a water body",
)
async def get_water_body_weather(
    water_body_id: str,
    force_refresh: bool = Query(False, description="Bypass cache and fetch fresh meteorological data"),
    weather_service: WeatherService = Depends(get_weather_service),
):
    """
    Retrieves real-time current conditions, 7-day meteorological forecast,
    and inferred rainfall-driven water-level trend for the specified water body.
    """
    try:
        return await weather_service.get_weather_for_water_body(
            water_body_id=water_body_id,
            force_refresh=force_refresh,
        )
    except WaterBodyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except MissingCoordinatesError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except (WeatherTimeoutError, WeatherRateLimitError, WeatherClientError) as exc:
        logger.error("Weather service error for %s: %s", water_body_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Weather data temporarily unavailable: {str(exc)}",
        )
    except Exception as exc:
        logger.error("Unexpected error retrieving weather for %s: %s", water_body_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error processing weather data.",
        )


@router.get(
    "/water-bodies/{water_body_id}/forecast",
    response_model=List[DailyForecastItem],
    summary="Get 7-day daily forecast only for a water body",
)
async def get_water_body_forecast(
    water_body_id: str,
    weather_service: WeatherService = Depends(get_weather_service),
):
    """
    Returns 7-day normalized daily forecast list for the specified water body.
    """
    try:
        return await weather_service.get_forecast_for_water_body(water_body_id)
    except WaterBodyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except MissingCoordinatesError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except (WeatherTimeoutError, WeatherRateLimitError, WeatherClientError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Forecast temporarily unavailable: {str(exc)}",
        )


@router.get(
    "/water-bodies/{water_body_id}/impact",
    response_model=WeatherImpactResponse,
    summary="Get qualitative rainfall-driven water-level trend and impact only",
)
async def get_water_body_weather_impact(
    water_body_id: str,
    weather_service: WeatherService = Depends(get_weather_service),
):
    """
    Returns qualitative rainfall impact and environmental water-level trend projection.
    """
    try:
        return await weather_service.get_weather_impact(water_body_id)
    except WaterBodyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except MissingCoordinatesError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except (WeatherTimeoutError, WeatherRateLimitError, WeatherClientError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Impact assessment temporarily unavailable: {str(exc)}",
        )
