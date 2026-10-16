import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import create_app
from app.db.database import get_db, SessionLocal
from app.db.models.water_body import WaterBody
from app.db.models.satellite_observation import SatelliteObservation
from app.services.weather import (
    OpenMeteoClient,
    WeatherService,
    WeatherCache,
    WaterLevelTrendEngine,
    WaterLevelTrend,
    WeatherConditionCode,
    ImpactLevel,
    ConfidenceLevel,
    DailyForecastItem,
    MissingCoordinatesError,
    WeatherTimeoutError,
    WeatherClientError,
    interpret_weather_code,
)
from app.services.telegram.models import TelegramUpdate, TelegramMessage, TelegramChat, TelegramUser
from app.services.telegram.handlers import TelegramCommandHandler


# Sample mock Open-Meteo API response payload
MOCK_OPEN_METEO_RESPONSE = {
    "latitude": 19.88,
    "longitude": 75.33,
    "timezone": "Asia/Kolkata",
    "current": {
        "temperature_2m": 28.4,
        "relative_humidity_2m": 67,
        "apparent_temperature": 30.1,
        "precipitation": 0.0,
        "rain": 0.0,
        "showers": 0.0,
        "weather_code": 1,
        "cloud_cover": 25,
        "wind_speed_10m": 11.2,
        "wind_direction_10m": 220,
    },
    "daily": {
        "time": [
            "2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19",
            "2026-10-20", "2026-10-21", "2026-10-22",
        ],
        "weather_code": [1, 61, 65, 80, 2, 0, 0],
        "temperature_2m_max": [29.5, 27.0, 25.5, 26.8, 29.0, 31.0, 31.5],
        "temperature_2m_min": [19.0, 18.5, 17.0, 17.5, 18.0, 19.0, 19.5],
        "precipitation_sum": [0.0, 12.5, 24.0, 6.5, 0.2, 0.0, 0.0],
        "rain_sum": [0.0, 12.5, 24.0, 6.5, 0.2, 0.0, 0.0],
        "precipitation_probability_max": [10, 75, 85, 60, 15, 5, 5],
        "wind_speed_10m_max": [12.0, 18.5, 22.0, 15.0, 10.0, 9.0, 8.5],
        "sunshine_duration": [28800.0, 14400.0, 7200.0, 18000.0, 32400.0, 36000.0, 36000.0],
        "et0_fao_evapotranspiration": [4.2, 3.1, 2.4, 3.5, 4.8, 5.2, 5.3],
    },
}


def test_weather_code_interpretation():
    text, code = interpret_weather_code(0)
    assert text == "Clear Sky"
    assert code == WeatherConditionCode.CLEAR

    text, code = interpret_weather_code(65)
    assert text == "Heavy Rain"
    assert code == WeatherConditionCode.HEAVY_RAIN

    text, code = interpret_weather_code(95)
    assert text == "Thunderstorm"
    assert code == WeatherConditionCode.THUNDERSTORM

    text, code = interpret_weather_code(9999)
    assert text == "Unknown"
    assert code == WeatherConditionCode.UNKNOWN


def test_open_meteo_client_parsing():
    client = OpenMeteoClient()
    current = client.parse_current_weather(MOCK_OPEN_METEO_RESPONSE)
    assert current.temperature_c == 28.4
    assert current.apparent_temperature_c == 30.1
    assert current.humidity_percent == 67
    assert current.wind_speed_kmh == 11.2
    assert current.condition == "Mainly Clear"

    daily = client.parse_daily_forecast(MOCK_OPEN_METEO_RESPONSE)
    assert len(daily) == 7
    assert daily[0].date == "2026-10-16"
    assert daily[0].temp_max_c == 29.5
    assert daily[0].sunshine_duration_hours == 8.0  # 28800 / 3600
    assert daily[2].precipitation_mm == 24.0
    assert daily[2].condition == "Heavy Rain"


def test_trend_engine_likely_rising():
    client = OpenMeteoClient()
    daily = client.parse_daily_forecast(MOCK_OPEN_METEO_RESPONSE)
    # Total precipitation is 12.5 + 24.0 + 6.5 + 0.2 = 43.2 mm
    recent_extents = [("2026-10-01", 1.20), ("2026-10-10", 1.28)]  # Expanding baseline (+6.7%)

    trend = WaterLevelTrendEngine.calculate_trend(daily, recent_apparent_extents=recent_extents)

    assert trend.trend == WaterLevelTrend.LIKELY_RISING
    assert trend.trend_arrow == "↑"
    assert trend.rainfall_impact == ImpactLevel.HIGH
    assert trend.internal_score >= 45
    assert trend.confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.MODERATE)
    assert "expanding" in trend.satellite_baseline_detail
    assert trend.forecast_rainfall_7d_mm == 43.2
    assert trend.wettest_day_date == "2026-10-18"
    assert trend.wettest_day_rainfall_mm == 24.0
    # Scientific sanity check: No numerical water depth mentioned in reason or response
    assert "meter" not in trend.expected_response.lower()
    assert "cm" not in trend.expected_response.lower()


def test_trend_engine_likely_falling():
    # Dry forecast
    dry_forecast = [
        DailyForecastItem(
            date=f"2026-10-{i:02d}",
            weather_code=0,
            condition="Clear Sky",
            condition_code=WeatherConditionCode.CLEAR,
            temp_max_c=34.0,
            temp_min_c=22.0,
            precipitation_mm=0.0,
            rain_mm=0.0,
            precipitation_probability_max=0,
            wind_speed_max_kmh=12.0,
            sunshine_duration_hours=10.5,
            et0_evapotranspiration_mm=5.5,
        )
        for i in range(1, 8)
    ]
    recent_extents = [("2026-09-20", 1.40), ("2026-10-05", 1.30)]  # Contracting baseline (-7.1%)

    trend = WaterLevelTrendEngine.calculate_trend(dry_forecast, recent_apparent_extents=recent_extents)

    assert trend.trend in (WaterLevelTrend.LIKELY_FALLING, WaterLevelTrend.POSSIBLY_FALLING)
    assert trend.trend_arrow in ("↓", "↘")
    assert trend.dryness_impact == ImpactLevel.HIGH
    assert trend.rainfall_impact == ImpactLevel.NONE
    assert trend.internal_score <= -18
    assert "contracting" in trend.satellite_baseline_detail


def test_trend_engine_stable():
    moderate_forecast = [
        DailyForecastItem(
            date=f"2026-10-{i:02d}",
            weather_code=2,
            condition="Partly Cloudy",
            condition_code=WeatherConditionCode.PARTLY_CLOUDY,
            temp_max_c=26.0,
            temp_min_c=18.0,
            precipitation_mm=0.8,
            rain_mm=0.8,
            precipitation_probability_max=20,
            wind_speed_max_kmh=10.0,
            sunshine_duration_hours=6.0,
            et0_evapotranspiration_mm=3.0,
        )
        for i in range(1, 8)
    ]
    recent_extents = [("2026-09-25", 1.25), ("2026-10-08", 1.255)]  # Stable (< 4% change)

    trend = WaterLevelTrendEngine.calculate_trend(moderate_forecast, recent_apparent_extents=recent_extents)

    assert trend.trend == WaterLevelTrend.STABLE
    assert trend.trend_arrow == "→"
    assert trend.trend_label == "Likely Stable"


def test_trend_engine_no_satellite_baseline():
    client = OpenMeteoClient()
    daily = client.parse_daily_forecast(MOCK_OPEN_METEO_RESPONSE)

    trend = WaterLevelTrendEngine.calculate_trend(daily, recent_apparent_extents=None)

    assert trend.satellite_baseline_status == "unavailable"
    assert "Satellite baseline unavailable" in trend.reason


def test_weather_cache():
    cache = WeatherCache(current_ttl=10, forecast_ttl=20)
    data = {"test": 123}

    cache.set("wb_weather", "lake-1", data, is_forecast=True)
    assert cache.get("wb_weather", "lake-1") == data

    # Non-existent key
    assert cache.get("wb_weather", "unknown") is None

    # Clear
    cache.clear()
    assert cache.get("wb_weather", "lake-1") is None


@pytest.mark.anyio
async def test_weather_service_with_mocked_client():
    mock_client = MagicMock(spec=OpenMeteoClient)
    mock_client.fetch_forecast = AsyncMock(return_value=MOCK_OPEN_METEO_RESPONSE)
    mock_client.parse_current_weather = MagicMock(
        return_value=OpenMeteoClient().parse_current_weather(MOCK_OPEN_METEO_RESPONSE)
    )
    mock_client.parse_daily_forecast = MagicMock(
        return_value=OpenMeteoClient().parse_daily_forecast(MOCK_OPEN_METEO_RESPONSE)
    )

    db = SessionLocal()
    try:
        # Create a test water body with centroid
        test_wb = WaterBody(
            name="Weather Test Lake",
            normalized_name="weather test lake",
            source="test",
            source_id="weather-test-1",
            centroid_lat=19.88,
            centroid_lon=75.33,
            area_sq_km=1.25,
            is_active=True,
        )
        db.add(test_wb)
        db.commit()
        db.refresh(test_wb)

        cache = WeatherCache()
        service = WeatherService(db=db, client=mock_client, cache=cache)

        weather = await service.get_weather_for_water_body(test_wb.id)
        assert weather.water_body_name == "Weather Test Lake"
        assert weather.location.latitude == 19.88
        assert weather.current.temperature_c == 28.4
        assert len(weather.forecast) == 7
        assert weather.water_level_trend.trend == WaterLevelTrend.LIKELY_RISING

        # Second call hits cache (fetch_forecast called only once)
        weather_cached = await service.get_weather_for_water_body(test_wb.id)
        assert weather_cached.water_body_id == test_wb.id
        assert mock_client.fetch_forecast.call_count == 1

        # Test forecast-only and impact-only methods
        forecast = await service.get_forecast_for_water_body(test_wb.id)
        assert len(forecast) == 7

        impact = await service.get_weather_impact(test_wb.id)
        assert impact.water_level_trend.trend == WaterLevelTrend.LIKELY_RISING

    finally:
        # Cleanup
        db.delete(test_wb)
        db.commit()
        db.close()


@pytest.mark.anyio
async def test_weather_service_missing_coordinates():
    db = SessionLocal()
    try:
        no_coord_wb = WaterBody(
            name="No Coords Lake",
            normalized_name="no coords lake",
            source="test",
            source_id="no-coords-test",
            centroid_lat=None,
            centroid_lon=None,
            is_active=True,
        )
        db.add(no_coord_wb)
        db.commit()
        db.refresh(no_coord_wb)

        service = WeatherService(db=db)
        with pytest.raises(MissingCoordinatesError):
            await service.get_weather_for_water_body(no_coord_wb.id)
    finally:
        db.delete(no_coord_wb)
        db.commit()
        db.close()


def test_weather_api_endpoints():
    app = create_app()
    client = TestClient(app)

    # 1. Status endpoint
    status_resp = client.get("/api/v1/weather/status")
    assert status_resp.status_code == 200
    status_json = status_resp.json()
    assert status_json["enabled"] is True
    assert status_json["provider"] == "Open-Meteo"
    assert status_json["requires_api_key"] is False

    # 2. 404 for non-existent water body
    resp_404 = client.get("/api/v1/weather/water-bodies/00000000-0000-0000-0000-000000000000")
    assert resp_404.status_code == 404

    # 3. Valid water body with mock
    db = SessionLocal()
    try:
        test_wb = WaterBody(
            name="API Test Lake",
            normalized_name="api test lake",
            source="test",
            source_id="api-test-1",
            centroid_lat=19.88,
            centroid_lon=75.33,
            is_active=True,
        )
        db.add(test_wb)
        db.commit()
        db.refresh(test_wb)

        with patch.object(OpenMeteoClient, "fetch_forecast", AsyncMock(return_value=MOCK_OPEN_METEO_RESPONSE)):
            # Full weather
            resp = client.get(f"/api/v1/weather/water-bodies/{test_wb.id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["water_body_name"] == "API Test Lake"
            assert "current" in data
            assert "forecast" in data
            assert "water_level_trend" in data
            assert data["water_level_trend"]["trend"] == "LIKELY_RISING"

            # Forecast only
            resp_fc = client.get(f"/api/v1/weather/water-bodies/{test_wb.id}/forecast")
            assert resp_fc.status_code == 200
            assert len(resp_fc.json()) == 7

            # Impact only
            resp_imp = client.get(f"/api/v1/weather/water-bodies/{test_wb.id}/impact")
            assert resp_imp.status_code == 200
            assert resp_imp.json()["water_level_trend"]["trend"] == "LIKELY_RISING"

    finally:
        db.delete(test_wb)
        db.commit()
        db.close()


@pytest.mark.anyio
async def test_telegram_weather_intent_integration():
    db = SessionLocal()
    try:
        test_wb = WaterBody(
            name="Telegram Weather Lake",
            normalized_name="telegram weather lake",
            source="test",
            source_id="tg-weath-1",
            centroid_lat=19.88,
            centroid_lon=75.33,
            is_active=True,
        )
        db.add(test_wb)
        db.commit()
        db.refresh(test_wb)

        mock_telegram_client = MagicMock()
        mock_telegram_client.send_message = AsyncMock()

        handler = TelegramCommandHandler(client=mock_telegram_client)

        with patch.object(OpenMeteoClient, "fetch_forecast", AsyncMock(return_value=MOCK_OPEN_METEO_RESPONSE)):
            # User asks: "What is the weather at Telegram Weather Lake?"
            msg = TelegramMessage(
                message_id=1,
                date=1700000000,
                chat=TelegramChat(id=777, type="private"),
                from_user=TelegramUser(id=777, is_bot=False, first_name="TestUser"),
                text="What is the weather at Telegram Weather Lake?",
            )
            await handler.handle_message(msg)

            assert mock_telegram_client.send_message.called
            call_args = mock_telegram_client.send_message.call_args[0]
            chat_id, text = call_args[0], call_args[1]
            assert chat_id == 777
            assert "Telegram Weather Lake" in text
            assert "Now:" in text
            assert "Today:" in text
            assert "Next 7 days:" in text
            assert "Overall:" in text

    finally:
        db.delete(test_wb)
        db.commit()
        db.close()
