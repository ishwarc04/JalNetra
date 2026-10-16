import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.models.water_body import WaterBody
from app.db.models.satellite_observation import SatelliteObservation
from app.services.satellite.image_resolver import (
    ObservationImageResolver,
    SUPPORTED_IMAGE_EXTENSIONS,
)
from app.services.telegram.intent_service import (
    TelegramIntentService,
    TelegramIntent,
)
from app.services.telegram.models import (
    TelegramMessage,
    TelegramChat,
    TelegramUser,
    TelegramCallbackQuery,
)
from app.services.telegram.client import TelegramClient
from app.services.telegram.handlers import TelegramCommandHandler


@pytest.fixture
def mock_telegram_client():
    client = MagicMock(spec=TelegramClient)
    client.is_configured = True
    client.send_message = AsyncMock(return_value=True)
    client.send_photo = AsyncMock(return_value=True)
    client.answer_callback_query = AsyncMock(return_value=True)
    client.get_me = AsyncMock(return_value={"id": 12345, "is_bot": True, "username": "jalNetra_Helperbot"})
    client.get_updates = AsyncMock(return_value=[])
    client.close = AsyncMock()
    return client


def make_msg(chat_id: int, text: str) -> TelegramMessage:
    return TelegramMessage(
        message_id=1,
        chat=TelegramChat(id=chat_id, type="private"),
        date=1729000000,
        text=text,
        from_user=TelegramUser(id=chat_id, is_bot=False, first_name="TestUser"),
    )


def make_callback(chat_id: int, data: str) -> TelegramCallbackQuery:
    return TelegramCallbackQuery(
        id="query_123",
        from_user=TelegramUser(id=chat_id, is_bot=False, first_name="TestUser"),
        message=make_msg(chat_id, ""),
        data=data,
    )


# ==============================================================================
# 1. IMAGE RESOLVER TESTS
# ==============================================================================

def test_image_resolver_valid_relative_and_absolute_paths(tmp_path: Path):
    """Test resolving images from relative, absolute, and observation directories."""
    wb_id = str(uuid.uuid4())
    obs_dir = tmp_path / "water_bodies" / wb_id / "observations" / "scene_1"
    obs_dir.mkdir(parents=True, exist_ok=True)
    img_file = obs_dir / "rgb.jpg"
    img_file.write_bytes(b"dummy_jpeg_data_content")

    # 1. Relative path 'water_bodies/...'
    obs1 = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb_id,
        external_scene_id="scene_1",
        sensing_date=datetime(2026, 10, 10, tzinfo=timezone.utc),
        local_visual_path=f"water_bodies/{wb_id}/observations/scene_1/rgb.jpg",
    )
    resolved = ObservationImageResolver.resolve_visual_image(obs1, data_dir=tmp_path)
    assert resolved is not None
    assert resolved.exists()
    assert resolved.name == "rgb.jpg"

    # 2. 'data/...' prefix
    obs2 = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb_id,
        external_scene_id="scene_1",
        sensing_date=datetime(2026, 10, 10, tzinfo=timezone.utc),
        local_visual_path=f"data/water_bodies/{wb_id}/observations/scene_1/rgb.jpg",
    )
    resolved2 = ObservationImageResolver.resolve_visual_image(obs2, data_dir=tmp_path)
    assert resolved2 is not None
    assert resolved2.exists()

    # 3. Absolute path
    obs3 = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb_id,
        external_scene_id="scene_1",
        sensing_date=datetime(2026, 10, 10, tzinfo=timezone.utc),
        local_visual_path=str(img_file.resolve()),
    )
    resolved3 = ObservationImageResolver.resolve_visual_image(obs3, data_dir=tmp_path)
    assert resolved3 is not None
    assert resolved3 == img_file.resolve()

    # 4. Directory convention scan when local_visual_path is missing
    obs4 = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb_id,
        external_scene_id="scene_1",
        sensing_date=datetime(2026, 10, 10, tzinfo=timezone.utc),
        local_visual_path=None,
    )
    resolved4 = ObservationImageResolver.resolve_visual_image(obs4, data_dir=tmp_path)
    assert resolved4 is not None
    assert resolved4.name == "rgb.jpg"


def test_image_resolver_invalid_and_traversal_paths(tmp_path: Path):
    """Test that zero-byte files, invalid extensions, and directory traversals return None."""
    wb_id = str(uuid.uuid4())
    obs_dir = tmp_path / "water_bodies" / wb_id / "observations" / "scene_2"
    obs_dir.mkdir(parents=True, exist_ok=True)

    # 1. 0-byte file
    zero_file = obs_dir / "rgb.jpg"
    zero_file.write_bytes(b"")
    obs_zero = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb_id,
        external_scene_id="scene_2",
        sensing_date=datetime(2026, 10, 10, tzinfo=timezone.utc),
        local_visual_path=f"water_bodies/{wb_id}/observations/scene_2/rgb.jpg",
    )
    assert ObservationImageResolver.resolve_visual_image(obs_zero, data_dir=tmp_path) is None

    # 2. Unsupported extension
    txt_file = obs_dir / "image.txt"
    txt_file.write_bytes(b"not an image")
    obs_txt = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb_id,
        external_scene_id="scene_2",
        sensing_date=datetime(2026, 10, 10, tzinfo=timezone.utc),
        local_visual_path=f"water_bodies/{wb_id}/observations/scene_2/image.txt",
    )
    assert ObservationImageResolver.resolve_visual_image(obs_txt, data_dir=tmp_path) is None

    # 3. Path traversal attempt
    obs_traversal = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb_id,
        external_scene_id="scene_2",
        sensing_date=datetime(2026, 10, 10, tzinfo=timezone.utc),
        local_visual_path="../../secret.jpg",
    )
    assert ObservationImageResolver.resolve_visual_image(obs_traversal, data_dir=tmp_path) is None


def test_get_latest_visual_observation_skips_missing_newest(db_session, tmp_path: Path):
    """
    Test newest-first search:
    If the newest observation's image file is missing,
    get_latest_visual_observation returns the older observation that HAS a valid file!
    """
    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Multi Observation Lake",
        normalized_name="multi observation lake",
        source="osm",
    )
    db_session.add(wb)
    db_session.commit()

    # Observation 1 (Older: 2026-10-01) - Has valid image file on disk
    obs_dir1 = tmp_path / "water_bodies" / wb.id / "observations" / "scene_older"
    obs_dir1.mkdir(parents=True, exist_ok=True)
    img_file1 = obs_dir1 / "rgb.jpg"
    img_file1.write_bytes(b"valid_image_bytes_123")

    obs_older = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb.id,
        external_scene_id="scene_older",
        sensing_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
        local_visual_path=f"water_bodies/{wb.id}/observations/scene_older/rgb.jpg",
    )

    # Observation 2 (Newer: 2026-10-10) - File is MISSING on disk
    obs_newer = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb.id,
        external_scene_id="scene_newer",
        sensing_date=datetime(2026, 10, 10, tzinfo=timezone.utc),
        local_visual_path=f"water_bodies/{wb.id}/observations/scene_newer/rgb.jpg",
    )

    db_session.add_all([obs_older, obs_newer])
    db_session.commit()

    # When querying latest, it should skip obs_newer and successfully return obs_older!
    result = ObservationImageResolver.get_latest_visual_observation(wb.id, db_session, data_dir=tmp_path)
    assert result is not None
    obs, path = result
    assert obs.id == obs_older.id
    assert path.name == "rgb.jpg"


# ==============================================================================
# 2. INTENT SERVICE TESTS
# ==============================================================================

def test_intent_classification_deterministic():
    wb1 = WaterBody(id="wb-1", name="Salim Ali Lake", normalized_name="salim ali lake")
    wb2 = WaterBody(id="wb-2", name="Chilika Lake", normalized_name="chilika lake")
    wb3 = WaterBody(id="wb-3", name="Ooty Lake", normalized_name="ooty lake")
    all_wbs = [wb1, wb2, wb3]

    intent_svc = TelegramIntentService()

    # 1. List
    res = intent_svc.classify_intent("list water bodies", 100, all_wbs)
    assert res.intent == TelegramIntent.LIST_WATER_BODIES

    res = intent_svc.classify_intent("what water bodies do you have?", 100, all_wbs)
    assert res.intent == TelegramIntent.LIST_WATER_BODIES

    # 2. Latest Image
    res = intent_svc.classify_intent("Give me the latest image of Salim Ali Lake", 100, all_wbs)
    assert res.intent == TelegramIntent.LATEST_IMAGE
    assert res.water_body == wb1

    res = intent_svc.classify_intent("Show satellite photo of ooty", 100, all_wbs)
    assert res.intent == TelegramIntent.LATEST_IMAGE
    assert res.water_body == wb3

    # 3. Location / Maps
    res = intent_svc.classify_intent("Where is Salim Ali Lake?", 100, all_wbs)
    assert res.intent == TelegramIntent.LOCATION
    assert res.water_body == wb1

    res = intent_svc.classify_intent("Open Chilika Lake on maps", 100, all_wbs)
    assert res.intent == TelegramIntent.LOCATION
    assert res.water_body == wb2

    # 4. Water quality
    res = intent_svc.classify_intent("What is the water quality of Chilika Lake?", 100, all_wbs)
    assert res.intent == TelegramIntent.WATER_QUALITY
    assert res.water_body == wb2

    # 5. Monitoring frequency
    res = intent_svc.classify_intent("How often does Salim Ali Lake change?", 100, all_wbs)
    assert res.intent == TelegramIntent.MONITORING_FREQUENCY
    assert res.water_body == wb1

    # 6. Today phrasing
    res = intent_svc.classify_intent("How is Salim Ali Lake today?", 100, all_wbs)
    assert res.intent == TelegramIntent.WATER_BODY_INFO
    assert res.water_body == wb1
    assert res.is_today_query is True


# ==============================================================================
# 3. CONVERSATIONAL CONTEXT FOLLOW-UP TESTS
# ==============================================================================

def test_conversational_context_multi_turn(mock_telegram_client, db_session, tmp_path):
    """
    Test conversational sequence:
    User: Tell me about Salim Ali Lake
    Bot: [summary]
    User: Show its image
    Bot: [photo]
    User: Where is it?
    Bot: [Google Maps]
    User: How is the water?
    Bot: [quality summary]
    """
    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Salim Ali Lake",
        normalized_name="salim ali lake",
        source="osm",
        centroid_lat=19.89,
        centroid_lon=75.34,
        area_sq_km=0.18,
    )
    db_session.add(wb)
    db_session.commit()

    # Add observation with image
    obs_dir = tmp_path / "water_bodies" / wb.id / "observations" / "scene_salim"
    obs_dir.mkdir(parents=True, exist_ok=True)
    img = obs_dir / "rgb.jpg"
    img.write_bytes(b"salim_ali_visual_bytes")

    obs = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb.id,
        external_scene_id="scene_salim",
        sensing_date=datetime(2026, 10, 10, tzinfo=timezone.utc),
        cloud_cover_percent=2.0,
        local_visual_path=f"water_bodies/{wb.id}/observations/scene_salim/rgb.jpg",
    )
    db_session.add(obs)
    db_session.commit()

    async def run():
        with patch.object(settings, "DATA_DIR", tmp_path):
            handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
            chat_id = 9999

            # 1. Turn 1: "Tell me about Salim Ali Lake"
            msg1 = make_msg(chat_id, "Tell me about Salim Ali Lake")
            await handler.handle_message(msg1)

            assert mock_telegram_client.send_message.call_count >= 1
            reply1 = mock_telegram_client.send_message.call_args[0][1]
            assert "SALIM ALI LAKE" in reply1
            # Context must now remember wb.id
            assert handler.intent_service.get_chat_context(chat_id) == wb.id

            mock_telegram_client.send_message.reset_mock()
            mock_telegram_client.send_photo.reset_mock()

            # 2. Turn 2: "Show its image" (Uses context!)
            msg2 = make_msg(chat_id, "Show its image")
            await handler.handle_message(msg2)

            mock_telegram_client.send_photo.assert_called_once()
            _, photo_kwargs = mock_telegram_client.send_photo.call_args
            assert photo_kwargs["chat_id"] == chat_id
            assert photo_kwargs["photo_bytes"] == b"salim_ali_visual_bytes"

            mock_telegram_client.send_message.reset_mock()
            mock_telegram_client.send_photo.reset_mock()

            # 3. Turn 3: "Where is it?" (Uses context!)
            msg3 = make_msg(chat_id, "Where is it?")
            await handler.handle_message(msg3)

            mock_telegram_client.send_message.assert_called_once()
            reply3 = mock_telegram_client.send_message.call_args[0][1]
            assert "Salim Ali Lake" in reply3
            assert "maps.google.com" in reply3 or "google.com/maps" in reply3

            mock_telegram_client.send_message.reset_mock()

            # 4. Turn 4: "How is the water?" (Uses context!)
            msg4 = make_msg(chat_id, "How is the water?")
            await handler.handle_message(msg4)

            mock_telegram_client.send_message.assert_called_once()
            reply4 = mock_telegram_client.send_message.call_args[0][1]
            assert "Water Quality" in reply4
            assert "Salim Ali Lake" in reply4

    asyncio.run(run())


# ==============================================================================
# 4. TELEGRAM CALLBACK QUERY TESTS
# ==============================================================================

def test_telegram_callback_queries(mock_telegram_client, db_session, tmp_path):
    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Chilika Lake",
        normalized_name="chilika lake",
        source="osm",
        centroid_lat=19.72,
        centroid_lon=85.32,
    )
    db_session.add(wb)
    db_session.commit()

    async def run():
        with patch.object(settings, "DATA_DIR", tmp_path):
            handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
            mock_telegram_client.answer_callback_query = AsyncMock(return_value=True)

            # 1. Quality button callback
            cb_qual = make_callback(777, f"wb_qual:{wb.id}")
            await handler.handle_callback_query(cb_qual)
            mock_telegram_client.answer_callback_query.assert_called_with("query_123")
            reply = mock_telegram_client.send_message.call_args[0][1]
            assert "Water Quality" in reply
            assert "Chilika Lake" in reply

            mock_telegram_client.send_message.reset_mock()

            # 2. Monitoring button callback
            cb_mon = make_callback(777, f"wb_mon:{wb.id}")
            await handler.handle_callback_query(cb_mon)
            reply = mock_telegram_client.send_message.call_args[0][1]
            assert "Monitoring History" in reply
            assert "Chilika Lake" in reply

    asyncio.run(run())


# ==============================================================================
# 5. REST API VISUAL STATUS & STREAMING TESTS
# ==============================================================================

def test_api_visual_status_and_streaming(client: TestClient, db_session, tmp_path: Path):
    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Ooty Lake",
        normalized_name="ooty lake",
        source="osm",
    )
    db_session.add(wb)
    db_session.commit()

    # 1. When 0 observations exist:
    res = client.get(f"/api/v1/water-bodies/{wb.id}/visual-status")
    assert res.status_code == 200
    data = res.json()
    assert data["observation_count"] == 0
    assert data["image_available"] is False

    # 2. Add an observation with file
    obs_dir = tmp_path / "water_bodies" / wb.id / "observations" / "scene_ooty"
    obs_dir.mkdir(parents=True, exist_ok=True)
    img_file = obs_dir / "rgb.jpg"
    img_file.write_bytes(b"ooty_test_jpeg_bytes")

    obs = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb.id,
        external_scene_id="scene_ooty",
        sensing_date=datetime(2026, 10, 10, tzinfo=timezone.utc),
        local_visual_path=f"water_bodies/{wb.id}/observations/scene_ooty/rgb.jpg",
    )
    db_session.add(obs)
    db_session.commit()

    with patch.object(settings, "DATA_DIR", tmp_path):
        # Check visual-status
        res2 = client.get(f"/api/v1/water-bodies/{wb.id}/visual-status")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["observation_count"] == 1
        assert data2["image_available"] is True
        assert data2["image_size_bytes"] == len(b"ooty_test_jpeg_bytes")

        # Test streaming endpoint
        res3 = client.get(f"/api/v1/water-bodies/{wb.id}/observations/{obs.id}/visual")
        assert res3.status_code == 200
        assert res3.headers["content-type"] == "image/jpeg"
        assert res3.content == b"ooty_test_jpeg_bytes"

        # Test non-existent observation returns 404
        bad_id = str(uuid.uuid4())
        res4 = client.get(f"/api/v1/water-bodies/{wb.id}/observations/{bad_id}/visual")
        assert res4.status_code == 404


# ==============================================================================
# 6. WATER SAFETY & SCIENTIFIC LIMITATIONS TESTS
# ==============================================================================

def test_water_safety_intents_and_context(mock_telegram_client, db_session):
    """
    Verifies that safety questions (drinkability, toxicity, bathing, water safety)
    are correctly classified and resolve conversational context naturally.
    """
    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Phewa Tal",
        normalized_name="phewa tal fewa taal फेवा ताल",
        country="Nepal",
        city="Pokhara",
    )
    db_session.add(wb)
    db_session.commit()

    all_wbs = [wb]
    svc = TelegramIntentService()
    chat_id = 8888

    # 1. Establish context
    r0 = svc.classify_intent("How is the water at Phewa Tal?", chat_id, all_wbs)
    assert r0.intent == TelegramIntent.WATER_QUALITY
    assert r0.water_body.id == wb.id

    # 2. Contextual follow-up: "Can I drink it?"
    r1 = svc.classify_intent("Can I drink it?", chat_id, all_wbs)
    assert r1.intent == TelegramIntent.DRINKABILITY
    assert r1.water_body.id == wb.id
    assert r1.context_used is True

    # 3. Contextual follow-up: "Is this water toxic?"
    r2 = svc.classify_intent("Is this water toxic?", chat_id, all_wbs)
    assert r2.intent == TelegramIntent.TOXICITY
    assert r2.water_body.id == wb.id

    # 4. Contextual follow-up: "Can I bathe here?"
    r3 = svc.classify_intent("Can I bathe here?", chat_id, all_wbs)
    assert r3.intent == TelegramIntent.BATHING_SAFETY
    assert r3.water_body.id == wb.id

    # 5. Contextual follow-up: "Will the water level increase?"
    r4 = svc.classify_intent("Will the water level increase?", chat_id, all_wbs)
    assert r4.intent == TelegramIntent.WATER_LEVEL_FORECAST
    assert r4.water_body.id == wb.id

    # 6. Contextual follow-up: "Will it rain?"
    r5 = svc.classify_intent("Will it rain?", chat_id, all_wbs)
    assert r5.intent == TelegramIntent.RAIN_FORECAST
    assert r5.water_body.id == wb.id


def test_safety_responses_scientific_limitations(mock_telegram_client, db_session):
    """
    Verifies strict safety rules:
    - NEVER say "Safe to drink"
    - NEVER say "The water is toxic" based solely on satellite data
    - ALWAYS include scientific disclaimer and note about laboratory testing
    """
    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Phewa Tal",
        normalized_name="phewa tal",
        country="Nepal",
        city="Pokhara",
    )
    db_session.add(wb)
    db_session.commit()

    async def run():
        handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
        chat_id = 7777

        # 1. Ask drinkability
        msg1 = make_msg(chat_id, "Is the water at Phewa Tal drinkable?")
        await handler.handle_message(msg1)
        mock_telegram_client.send_message.assert_called_once()
        reply1 = mock_telegram_client.send_message.call_args[0][1]

        assert "Drinking Water Assessment" in reply1
        assert "cannot certify this water as safe for drinking" in reply1.lower()
        assert "laboratory testing" in reply1.lower()
        # MUST NOT say safe to drink
        assert "is safe to drink" not in reply1.lower()
        assert "is safe for drinking" not in reply1.lower()

        mock_telegram_client.send_message.reset_mock()

        # 2. Ask toxicity
        msg2 = make_msg(chat_id, "Is this water toxic?")
        await handler.handle_message(msg2)
        reply2 = mock_telegram_client.send_message.call_args[0][1]

        assert "Toxicity Assessment" in reply2
        assert "cannot determine water toxicity from satellite" in reply2.lower()
        assert "no laboratory toxicity" in reply2.lower()
        assert "the water is toxic" not in reply2.lower()

        mock_telegram_client.send_message.reset_mock()

        # 3. Ask bathing safety
        msg3 = make_msg(chat_id, "Can I bathe here?")
        await handler.handle_message(msg3)
        reply3 = mock_telegram_client.send_message.call_args[0][1]

        assert "Bathing Safety" in reply3
        assert "cannot certify that bathing is safe" in reply3.lower()
        assert "safe for swimming" not in reply3.lower()

    asyncio.run(run())


def test_compound_and_weather_trend_responses(mock_telegram_client, db_session):
    """
    Tests combined questions like:
    - 'Is the water drinkable and will the level increase?'
    - 'How is the water and what is the weather?'
    """
    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Phewa Tal",
        normalized_name="phewa tal",
        centroid_lat=28.21,
        centroid_lon=83.95,
        country="Nepal",
        city="Pokhara",
    )
    db_session.add(wb)
    db_session.commit()

    from app.services.weather.models import (
        WeatherResponse,
        CurrentWeather,
        DailyForecastItem,
        WaterLevelTrendInterpretation,
        WaterLevelTrend,
        ImpactLevel,
        ConfidenceLevel,
        LocationInfo,
        WeatherConditionCode,
    )

    mock_weather = WeatherResponse(
        water_body_id=wb.id,
        water_body_name=wb.name,
        fetched_at="2026-10-16T12:00:00Z",
        from_cache=False,
        cache_ttl_remaining_seconds=3600,
        location=LocationInfo(latitude=28.21, longitude=83.95, timezone="Asia/Kathmandu"),
        current=CurrentWeather(
            temperature_c=24.0,
            apparent_temperature_c=25.0,
            humidity_percent=65,
            precipitation_mm=2.0,
            rain_mm=2.0,
            cloud_cover_percent=75,
            wind_speed_kmh=8.0,
            wind_direction_deg=180,
            weather_code=3,
            condition="Cloudy",
            condition_code=WeatherConditionCode.OVERCAST,
        ),
        forecast=[
            DailyForecastItem(
                date="2026-10-16",
                weather_code=61,
                condition="Rain",
                condition_code=WeatherConditionCode.RAIN,
                temp_max_c=25.0,
                temp_min_c=18.0,
                precipitation_mm=5.0,
                rain_mm=5.0,
                precipitation_probability_max=80,
            ),
            DailyForecastItem(
                date="2026-10-17",
                weather_code=61,
                condition="Heavy Rain",
                condition_code=WeatherConditionCode.HEAVY_RAIN,
                temp_max_c=24.0,
                temp_min_c=17.0,
                precipitation_mm=20.0,
                rain_mm=20.0,
                precipitation_probability_max=90,
            ),
        ],
        water_level_trend=WaterLevelTrendInterpretation(
            trend=WaterLevelTrend.LIKELY_RISING,
            trend_arrow="↑",
            trend_label="Likely Rising",
            internal_score=65,
            confidence=ConfidenceLevel.MODERATE,
            rainfall_impact=ImpactLevel.HIGH,
            dryness_impact=ImpactLevel.LOW,
            forecast_rainfall_7d_mm=25.0,
            rain_probability_label="High",
            reason="Significant rainfall forecast over coming days.",
            expected_response="Water extent likely to expand.",
            satellite_baseline_status="available",
        ),
    )

    async def run():
        handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
        chat_id = 6666

        with patch("app.services.weather.WeatherService.get_weather_for_water_body", AsyncMock(return_value=mock_weather)):
            # 1. Ask combined drinkability + water level
            msg1 = make_msg(chat_id, "Is the water at Phewa Tal drinkable and will the level increase?")
            await handler.handle_message(msg1)
            assert mock_telegram_client.send_message.call_count >= 1
            reply1 = mock_telegram_client.send_message.call_args[0][1]

            assert "Drinking Water Assessment" in reply1
            assert "Water-Level Outlook" in reply1
            assert "Likely Rising" in reply1

            mock_telegram_client.send_message.reset_mock()

            # 2. Ask combined water quality + weather
            msg2 = make_msg(chat_id, "How is the water and what is the weather?")
            await handler.handle_message(msg2)
            reply2 = mock_telegram_client.send_message.call_args[0][1]

            assert "Water Quality Overview" in reply2
            assert "Phewa Tal Weather" in reply2

    asyncio.run(run())


def test_image_delivery_sendphoto_verification(mock_telegram_client, db_session, tmp_path):
    """
    Verifies that:
    1. Valid local image file is found.
    2. sendPhoto is called with actual bytes (NOT filesystem path text).
    3. Correct chat ID, photo filename, caption, and inline buttons are passed.
    4. No internal local paths are leaked in text.
    """
    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Phewa Tal",
        normalized_name="phewa tal",
        centroid_lat=28.21,
        centroid_lon=83.95,
    )
    db_session.add(wb)
    db_session.commit()

    obs_dir = tmp_path / "water_bodies" / wb.id / "observations" / "scene_phewa_latest"
    obs_dir.mkdir(parents=True, exist_ok=True)
    real_img = obs_dir / "rgb.jpg"
    test_binary = b"SIMULATED_SENTINEL_2_PHOTO_BYTES"
    real_img.write_bytes(test_binary)

    obs = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb.id,
        external_scene_id="scene_phewa_latest",
        sensing_date=datetime(2026, 10, 11, tzinfo=timezone.utc),
        cloud_cover_percent=0.0,
        local_visual_path=f"water_bodies/{wb.id}/observations/scene_phewa_latest/rgb.jpg",
    )
    db_session.add(obs)
    db_session.commit()

    async def run():
        with patch.object(settings, "DATA_DIR", tmp_path):
            handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
            chat_id = 5555

            # Ask for photo
            msg = make_msg(chat_id, "Show me the latest image of Phewa Tal")
            await handler.handle_message(msg)

            # sendPhoto MUST have been called
            mock_telegram_client.send_photo.assert_called_once()
            _, kwargs = mock_telegram_client.send_photo.call_args

            assert kwargs["chat_id"] == chat_id
            assert kwargs["photo_bytes"] == test_binary
            assert kwargs["filename"] == "rgb.jpg"
            caption = kwargs["caption"]
            assert "Phewa Tal" in caption
            assert "11 Oct 2026" in caption
            assert "Cloud cover: 0.0%" in caption

            # Verify buttons on photo
            assert "reply_markup" in kwargs
            buttons = kwargs["reply_markup"]["inline_keyboard"]
            assert len(buttons) >= 1
            button_texts = [b["text"] for row in buttons for b in row]
            assert "🗺 Location" in button_texts
            assert "💧 Water Quality" in button_texts

            # Verify NO internal filesystem path was sent as plain text message
            if mock_telegram_client.send_message.called:
                for call in mock_telegram_client.send_message.call_args_list:
                    sent_text = call[0][1]
                    assert str(tmp_path) not in sent_text
                    assert "observations/scene_phewa_latest" not in sent_text

    asyncio.run(run())

