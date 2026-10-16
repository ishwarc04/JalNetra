import logging
from typing import Dict, Any, Optional, Tuple
import httpx

from app.services.weather.models import (
    CurrentWeather,
    DailyForecastItem,
    WeatherConditionCode,
)

logger = logging.getLogger("jalnetra.weather.client")

OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherClientError(Exception):
    """Base exception for weather client failures."""
    pass


class WeatherTimeoutError(WeatherClientError):
    """Raised when the weather API call times out."""
    pass


class WeatherRateLimitError(WeatherClientError):
    """Raised when Open-Meteo returns rate limit status (HTTP 429)."""
    pass


WMO_WEATHER_MAP: Dict[int, Tuple[str, WeatherConditionCode]] = {
    0: ("Clear Sky", WeatherConditionCode.CLEAR),
    1: ("Mainly Clear", WeatherConditionCode.CLEAR),
    2: ("Partly Cloudy", WeatherConditionCode.PARTLY_CLOUDY),
    3: ("Overcast", WeatherConditionCode.OVERCAST),
    45: ("Fog", WeatherConditionCode.FOG),
    48: ("Depositing Rime Fog", WeatherConditionCode.FOG),
    51: ("Light Drizzle", WeatherConditionCode.DRIZZLE),
    53: ("Moderate Drizzle", WeatherConditionCode.DRIZZLE),
    55: ("Dense Drizzle", WeatherConditionCode.DRIZZLE),
    56: ("Light Freezing Drizzle", WeatherConditionCode.DRIZZLE),
    57: ("Dense Freezing Drizzle", WeatherConditionCode.DRIZZLE),
    61: ("Slight Rain", WeatherConditionCode.RAIN),
    63: ("Moderate Rain", WeatherConditionCode.RAIN),
    65: ("Heavy Rain", WeatherConditionCode.HEAVY_RAIN),
    66: ("Light Freezing Rain", WeatherConditionCode.RAIN),
    67: ("Heavy Freezing Rain", WeatherConditionCode.HEAVY_RAIN),
    71: ("Slight Snow", WeatherConditionCode.SNOW),
    73: ("Moderate Snow", WeatherConditionCode.SNOW),
    75: ("Heavy Snow", WeatherConditionCode.SNOW),
    77: ("Snow Grains", WeatherConditionCode.SNOW),
    80: ("Slight Rain Showers", WeatherConditionCode.RAIN),
    81: ("Moderate Rain Showers", WeatherConditionCode.RAIN),
    82: ("Violent Rain Showers", WeatherConditionCode.HEAVY_RAIN),
    85: ("Slight Snow Showers", WeatherConditionCode.SNOW),
    86: ("Heavy Snow Showers", WeatherConditionCode.SNOW),
    95: ("Thunderstorm", WeatherConditionCode.THUNDERSTORM),
    96: ("Thunderstorm with Light Hail", WeatherConditionCode.THUNDERSTORM),
    99: ("Thunderstorm with Heavy Hail", WeatherConditionCode.THUNDERSTORM),
}


def interpret_weather_code(code: int) -> Tuple[str, WeatherConditionCode]:
    """Translates WMO weather code to human-friendly text and condition category."""
    return WMO_WEATHER_MAP.get(code, ("Unknown", WeatherConditionCode.UNKNOWN))


class OpenMeteoClient:
    """
    Asynchronous client for Open-Meteo Weather Forecast API.
    Does not require an API key or registration.
    """

    def __init__(self, base_url: str = OPEN_METEO_BASE_URL, timeout: float = 10.0):
        self.base_url = base_url
        self.timeout = timeout

    async def fetch_forecast(
        self,
        latitude: float,
        longitude: float,
        forecast_days: int = 7,
    ) -> Dict[str, Any]:
        """
        Calls Open-Meteo with required current and daily variables.
        """
        params = {
            "latitude": round(latitude, 4),
            "longitude": round(longitude, 4),
            "current": (
                "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "precipitation,rain,showers,weather_code,cloud_cover,"
                "wind_speed_10m,wind_direction_10m"
            ),
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_sum,rain_sum,precipitation_probability_max,"
                "wind_speed_10m_max,sunshine_duration,et0_fao_evapotranspiration"
            ),
            "timezone": "auto",
            "forecast_days": min(max(forecast_days, 1), 16),
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(self.base_url, params=params)

                if response.status_code == 429:
                    raise WeatherRateLimitError("Open-Meteo rate limit reached. Please try again later.")

                response.raise_for_status()
                data = response.json()
                return data

        except httpx.TimeoutException as exc:
            logger.warning("Open-Meteo timeout for lat=%s lon=%s: %s", latitude, longitude, exc)
            raise WeatherTimeoutError("Weather forecast request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning("Open-Meteo HTTP error %s: %s", exc.response.status_code, exc)
            raise WeatherClientError(f"Weather API error: HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            if isinstance(exc, WeatherClientError):
                raise
    def fetch_forecast_sync(
        self,
        latitude: float,
        longitude: float,
        forecast_days: int = 7,
    ) -> Dict[str, Any]:
        """Synchronous version of fetch_forecast for sync context callers like AIService."""
        params = {
            "latitude": round(latitude, 4),
            "longitude": round(longitude, 4),
            "current": (
                "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "precipitation,rain,showers,weather_code,cloud_cover,"
                "wind_speed_10m,wind_direction_10m"
            ),
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_sum,rain_sum,precipitation_probability_max,"
                "wind_speed_10m_max,sunshine_duration,et0_fao_evapotranspiration"
            ),
            "timezone": "auto",
            "forecast_days": min(max(forecast_days, 1), 16),
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(self.base_url, params=params)

                if response.status_code == 429:
                    raise WeatherRateLimitError("Open-Meteo rate limit reached. Please try again later.")

                response.raise_for_status()
                return response.json()

        except httpx.TimeoutException as exc:
            logger.warning("Open-Meteo sync timeout for lat=%s lon=%s: %s", latitude, longitude, exc)
            raise WeatherTimeoutError("Weather forecast request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning("Open-Meteo sync HTTP error %s: %s", exc.response.status_code, exc)
            raise WeatherClientError(f"Weather API error: HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            if isinstance(exc, WeatherClientError):
                raise
            logger.warning("Open-Meteo sync connection error: %s", exc)
            raise WeatherClientError(f"Failed to connect to Weather API: {str(exc)}") from exc

    def parse_current_weather(self, data: Dict[str, Any]) -> CurrentWeather:
        """Parses and normalizes current weather fields from Open-Meteo response."""
        curr = data.get("current", {})
        code = curr.get("weather_code", 0)
        cond_text, cond_code = interpret_weather_code(code)

        return CurrentWeather(
            temperature_c=float(curr.get("temperature_2m", 0.0)),
            apparent_temperature_c=float(curr.get("apparent_temperature", curr.get("temperature_2m", 0.0))),
            humidity_percent=int(curr.get("relative_humidity_2m", 50)),
            precipitation_mm=float(curr.get("precipitation", 0.0)),
            rain_mm=float(curr.get("rain", 0.0)),
            cloud_cover_percent=int(curr.get("cloud_cover", 0)),
            wind_speed_kmh=float(curr.get("wind_speed_10m", 0.0)),
            wind_direction_deg=int(curr.get("wind_direction_10m")) if curr.get("wind_direction_10m") is not None else None,
            weather_code=code,
            condition=cond_text,
            condition_code=cond_code,
        )

    def parse_daily_forecast(self, data: Dict[str, Any]) -> list[DailyForecastItem]:
        """Parses and normalizes 7-10 day daily forecast from Open-Meteo response."""
        daily = data.get("daily", {})
        times = daily.get("time", [])
        codes = daily.get("weather_code", [])
        temp_maxs = daily.get("temperature_2m_max", [])
        temp_mins = daily.get("temperature_2m_min", [])
        precip_sums = daily.get("precipitation_sum", [])
        rain_sums = daily.get("rain_sum", [])
        precip_probs = daily.get("precipitation_probability_max", [])
        wind_maxs = daily.get("wind_speed_10m_max", [])
        sunshines = daily.get("sunshine_duration", [])
        et0s = daily.get("et0_fao_evapotranspiration", [])

        items: list[DailyForecastItem] = []
        for i, dt in enumerate(times):
            code = codes[i] if i < len(codes) else 0
            cond_text, cond_code = interpret_weather_code(code)

            # Sunshine duration is returned in seconds by Open-Meteo -> convert to hours
            sunshine_hrs = None
            if i < len(sunshines) and sunshines[i] is not None:
                sunshine_hrs = round(float(sunshines[i]) / 3600.0, 1)

            et0_val = None
            if i < len(et0s) and et0s[i] is not None:
                et0_val = round(float(et0s[i]), 2)

            precip_prob = None
            if i < len(precip_probs) and precip_probs[i] is not None:
                precip_prob = int(precip_probs[i])

            wind_max = None
            if i < len(wind_maxs) and wind_maxs[i] is not None:
                wind_max = float(wind_maxs[i])

            items.append(
                DailyForecastItem(
                    date=str(dt),
                    weather_code=code,
                    condition=cond_text,
                    condition_code=cond_code,
                    temp_max_c=float(temp_maxs[i]) if i < len(temp_maxs) else 0.0,
                    temp_min_c=float(temp_mins[i]) if i < len(temp_mins) else 0.0,
                    precipitation_mm=float(precip_sums[i]) if i < len(precip_sums) else 0.0,
                    rain_mm=float(rain_sums[i]) if i < len(rain_sums) else 0.0,
                    precipitation_probability_max=precip_prob,
                    wind_speed_max_kmh=wind_max,
                    sunshine_duration_hours=sunshine_hrs,
                    et0_evapotranspiration_mm=et0_val,
                )
            )

        return items
