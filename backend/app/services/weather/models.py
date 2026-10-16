from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class WeatherConditionCode(str, Enum):
    CLEAR = "clear"
    PARTLY_CLOUDY = "partly_cloudy"
    OVERCAST = "overcast"
    FOG = "fog"
    DRIZZLE = "drizzle"
    RAIN = "rain"
    HEAVY_RAIN = "heavy_rain"
    THUNDERSTORM = "thunderstorm"
    SNOW = "snow"
    UNKNOWN = "unknown"


class WaterLevelTrend(str, Enum):
    LIKELY_RISING = "LIKELY_RISING"
    POSSIBLY_RISING = "POSSIBLY_RISING"
    STABLE = "STABLE"
    POSSIBLY_FALLING = "POSSIBLY_FALLING"
    LIKELY_FALLING = "LIKELY_FALLING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ImpactLevel(str, Enum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    NONE = "NONE"


class ConfidenceLevel(str, Enum):
    HIGH = "High"
    MODERATE = "Moderate"
    LOW = "Low"


class CurrentWeather(BaseModel):
    temperature_c: float
    apparent_temperature_c: float
    humidity_percent: int
    precipitation_mm: float
    rain_mm: float
    cloud_cover_percent: int
    wind_speed_kmh: float
    wind_direction_deg: Optional[int] = None
    weather_code: int
    condition: str
    condition_code: WeatherConditionCode = WeatherConditionCode.CLEAR


class DailyForecastItem(BaseModel):
    date: str
    weather_code: int
    condition: str
    condition_code: WeatherConditionCode = WeatherConditionCode.CLEAR
    temp_max_c: float
    temp_min_c: float
    precipitation_mm: float
    rain_mm: float
    precipitation_probability_max: Optional[int] = None
    wind_speed_max_kmh: Optional[float] = None
    sunshine_duration_hours: Optional[float] = None
    et0_evapotranspiration_mm: Optional[float] = None


class WaterLevelTrendInterpretation(BaseModel):
    trend: WaterLevelTrend
    trend_arrow: str
    trend_label: str
    internal_score: int = Field(ge=-100, le=100)
    confidence: ConfidenceLevel
    rainfall_impact: ImpactLevel
    dryness_impact: ImpactLevel
    forecast_rainfall_7d_mm: float
    wettest_day_date: Optional[str] = None
    wettest_day_rainfall_mm: Optional[float] = None
    rain_probability_label: str
    reason: str
    expected_response: str
    satellite_baseline_status: str  # "available" | "unavailable"
    satellite_baseline_detail: Optional[str] = None
    disclaimer: str = (
        "Rainfall-driven water-level trend is an inferred environmental signal based on meteorological forecast "
        "and satellite baseline. It is not a direct measurement of water depth, reservoir elevation, or volume."
    )


class LocationInfo(BaseModel):
    latitude: float
    longitude: float
    timezone: str


class WeatherResponse(BaseModel):
    water_body_id: str
    water_body_name: str
    location: LocationInfo
    provider: str = "Open-Meteo"
    current: CurrentWeather
    forecast: List[DailyForecastItem]
    water_level_trend: WaterLevelTrendInterpretation
    fetched_at: str


class WeatherImpactResponse(BaseModel):
    water_body_id: str
    water_body_name: str
    provider: str = "Open-Meteo"
    water_level_trend: WaterLevelTrendInterpretation
    fetched_at: str


class WeatherStatusResponse(BaseModel):
    enabled: bool = True
    provider: str = "Open-Meteo"
    configured: bool = True
    requires_api_key: bool = False
    details: str = "Standard public Open-Meteo Weather Forecast API"
