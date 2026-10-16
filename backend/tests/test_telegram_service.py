import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.telegram import (
    TelegramClient,
    TelegramCommandHandler,
    TelegramBotService,
    TelegramMessage,
    TelegramChat,
    TelegramUser,
)


@pytest.fixture
def mock_telegram_client():
    client = MagicMock(spec=TelegramClient)
    client.is_configured = True
    client.send_message = AsyncMock(return_value=True)
    client.send_photo = AsyncMock(return_value=True)
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


def test_telegram_status_endpoint(client: TestClient):
    """GET /api/v1/telegram/status returns connection status without exposing tokens."""
    resp = client.get("/api/v1/telegram/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "configured" in data
    assert "connected" in data
    assert "bot_username" in data
    assert "token" not in data
    assert "bot_token" not in data


def test_telegram_start_command(mock_telegram_client):
    """Test /start returns welcome message."""
    async def run():
        handler = TelegramCommandHandler(mock_telegram_client)
        msg = make_msg(123, "/start")
        await handler.handle_message(msg)

        mock_telegram_client.send_message.assert_called_once()
        args = mock_telegram_client.send_message.call_args[0]
        assert args[0] == 123
        assert "Welcome to JalNetra 2.0" in args[1]

    asyncio.run(run())


def test_telegram_help_command(mock_telegram_client):
    """Test /help lists all available commands."""
    async def run():
        handler = TelegramCommandHandler(mock_telegram_client)
        msg = make_msg(123, "/help")
        await handler.handle_message(msg)

        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "/start" in reply
        assert "/help" in reply
        assert "/ping" in reply
        assert "/status" in reply
        assert "/list" in reply
        assert "/waterbody" in reply
        assert "/ai <question>" in reply

    asyncio.run(run())


def test_telegram_ping_command(mock_telegram_client):
    """Test /ping returns connectivity confirmation."""
    async def run():
        handler = TelegramCommandHandler(mock_telegram_client)
        msg = make_msg(123, "/ping")
        await handler.handle_message(msg)

        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "JalNetra Telegram Bot is working" in reply
        assert "Telegram API: OK" in reply

    asyncio.run(run())


def test_telegram_status_command(mock_telegram_client):
    """Test /status returns system status without secrets."""
    async def run():
        mock_ai = MagicMock()
        mock_ai.get_status.return_value = MagicMock(configured=True)
        handler = TelegramCommandHandler(mock_telegram_client, ai_service=mock_ai)

        msg = make_msg(123, "/status")
        await handler.handle_message(msg)

        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "JalNetra Status" in reply
        assert "Backend: ONLINE" in reply
        assert "Telegram: CONNECTED" in reply

    asyncio.run(run())


def test_telegram_ai_command(mock_telegram_client):
    """Test /ai <question> dispatches to AI service."""
    async def run():
        mock_ai = MagicMock()
        mock_ai.generate_general_response.return_value = "JalNetra monitors lakes and reservoirs."
        handler = TelegramCommandHandler(mock_telegram_client, ai_service=mock_ai)

        msg = make_msg(123, "/ai What is JalNetra?")
        await handler.handle_message(msg)

        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "🤖 JalNetra AI" in reply
        assert "JalNetra monitors lakes and reservoirs." in reply

    asyncio.run(run())


def test_telegram_ai_security_rejection(mock_telegram_client):
    """Verify that administrative actions via /ai are rejected as read-only."""
    async def run():
        mock_ai = MagicMock()
        handler = TelegramCommandHandler(mock_telegram_client, ai_service=mock_ai)

        msg = make_msg(123, "/ai delete database")
        await handler.handle_message(msg)

        # AI service should NOT be called
        mock_ai.generate_general_response.assert_not_called()
        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "read-only" in reply

    asyncio.run(run())


def test_telegram_chat_authorization():
    """Verify TELEGRAM_ALLOWED_CHAT_IDS restricts access."""
    async def run():
        client = MagicMock(spec=TelegramClient)
        client.send_message = AsyncMock(return_value=True)

        with patch.object(settings, "TELEGRAM_ALLOWED_CHAT_IDS", "111,222"):
            handler = TelegramCommandHandler(client)
            assert handler.is_chat_allowed(111) is True
            assert handler.is_chat_allowed(222) is True
            assert handler.is_chat_allowed(999) is False

            # Attempt from unauthorized user
            msg = make_msg(999, "/ping")
            await handler.handle_message(msg)
            reply = client.send_message.call_args[0][1]
            assert "Unauthorized" in reply

    asyncio.run(run())


def test_telegram_bot_service_graceful_on_auth_failure():
    """When get_me returns None, bot service does not raise and connected remains False."""
    async def run():
        client = MagicMock(spec=TelegramClient)
        client.get_me = AsyncMock(return_value=None)
        client.close = AsyncMock()

        bot = TelegramBotService(client)
        with patch.object(settings, "TELEGRAM_ENABLED", True):
            with patch.object(settings, "TELEGRAM_BOT_TOKEN", "bad_token"):
                await bot.start()
                assert bot.is_connected is False
                await bot.stop()

    asyncio.run(run())


def test_telegram_list_empty(mock_telegram_client, db_session):
    """Test /list when no water bodies are registered."""
    async def run():
        handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
        msg = make_msg(123, "/list")
        await handler.handle_message(msg)

        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "No water bodies are currently available in JalNetra" in reply

    asyncio.run(run())


def test_telegram_list_with_data(mock_telegram_client, db_session):
    """Test /list displays registered water bodies dynamically."""
    import uuid
    from app.db.models.water_body import WaterBody

    wb1 = WaterBody(
        id=str(uuid.uuid4()),
        name="Chilika Lake",
        normalized_name="chilika lake",
        source="osm",
        country="India",
        state_province="Odisha",
    )
    wb2 = WaterBody(
        id=str(uuid.uuid4()),
        name="Ooty Lake",
        normalized_name="ooty lake",
        source="osm",
        country="India",
        state_province="Tamil Nadu",
    )
    db_session.add_all([wb1, wb2])
    db_session.commit()

    async def run():
        handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
        msg = make_msg(123, "/list")
        await handler.handle_message(msg)

        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "JalNetra Water Bodies" in reply
        assert "Chilika Lake" in reply
        assert "Ooty Lake" in reply
        assert "/waterbody" in reply

    asyncio.run(run())


def test_telegram_waterbody_empty_query(mock_telegram_client, db_session):
    """Test /waterbody without parameters prompts usage instructions."""
    async def run():
        handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
        msg = make_msg(123, "/waterbody")
        await handler.handle_message(msg)

        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "Please specify a water body name" in reply

    asyncio.run(run())


def test_telegram_waterbody_not_found(mock_telegram_client, db_session):
    """Test /waterbody with unknown name suggests /list."""
    async def run():
        handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
        msg = make_msg(123, "/waterbody Atlantis Reservoir")
        await handler.handle_message(msg)

        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "Water body not found" in reply
        assert "/list" in reply

    asyncio.run(run())


def test_telegram_waterbody_disambiguation(mock_telegram_client, db_session):
    """Test /waterbody substring query matching multiple water bodies returns disambiguation list."""
    import uuid
    from app.db.models.water_body import WaterBody

    wb1 = WaterBody(
        id=str(uuid.uuid4()),
        name="Pichola Lake",
        normalized_name="pichola lake",
        source="osm",
    )
    wb2 = WaterBody(
        id=str(uuid.uuid4()),
        name="Fateh Sagar Lake",
        normalized_name="fateh sagar lake",
        source="osm",
    )
    db_session.add_all([wb1, wb2])
    db_session.commit()

    async def run():
        handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
        msg = make_msg(123, "/waterbody lake")
        await handler.handle_message(msg)

        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "multiple water bodies matching" in reply
        assert "Pichola Lake" in reply
        assert "Fateh Sagar Lake" in reply

    asyncio.run(run())


def test_telegram_waterbody_exact_match_no_photo(mock_telegram_client, db_session):
    """Test /waterbody returns structured summary message without photo when no local image exists."""
    import uuid
    from app.db.models.water_body import WaterBody

    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Chilika Lake",
        normalized_name="chilika lake",
        source="osm",
        country="India",
        state_province="Odisha",
        area_sq_km=1165.0,
    )
    db_session.add(wb)
    db_session.commit()

    async def run():
        handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
        msg = make_msg(123, "/waterbody Chilika Lake")
        await handler.handle_message(msg)

        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "CHILIKA LAKE" in reply
        assert "Location" in reply
        assert "Surface Area" in reply
        assert "Estimated Water Volume" in reply
        assert "Latest Observation" in reply
        assert "Water Quality" in reply
        mock_telegram_client.send_photo.assert_not_called()

    asyncio.run(run())


def test_telegram_waterbody_exact_match_with_photo(mock_telegram_client, db_session, tmp_path):
    """Test /waterbody returns summary and uploads photo when a local visual image file exists on disk."""
    import uuid
    from datetime import datetime, timezone
    from app.db.models.water_body import WaterBody
    from app.db.models.satellite_observation import SatelliteObservation

    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Hussain Sagar",
        normalized_name="hussain sagar",
        source="osm",
        country="India",
        state_province="Telangana",
        city="Hyderabad",
        area_sq_km=4.4,
    )
    db_session.add(wb)
    db_session.commit()

    # Create dummy image file on disk in tmp_path
    rel_path = f"water_bodies/{wb.id}/observations/test_scene/rgb.jpg"
    img_file = tmp_path / rel_path
    img_file.parent.mkdir(parents=True, exist_ok=True)
    img_file.write_bytes(b"dummy_jpeg_content_12345")

    obs = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb.id,
        sensing_date=datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc),
        provider="copernicus",
        external_scene_id="test_scene",
        cloud_cover_percent=2.5,
        derived_water_area_sq_km=4.0,
        local_visual_path=rel_path,
    )
    db_session.add(obs)
    db_session.commit()

    async def run():
        with patch.object(settings, "DATA_DIR", tmp_path):
            handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
            msg = make_msg(123, "/waterbody Hussain Sagar")
            await handler.handle_message(msg)

            # Assert summary message sent
            mock_telegram_client.send_message.assert_called_once()
            reply = mock_telegram_client.send_message.call_args[0][1]
            assert "HUSSAIN SAGAR" in reply

            # Assert send_photo called with file content
            mock_telegram_client.send_photo.assert_called_once()
            _, photo_kwargs = mock_telegram_client.send_photo.call_args
            assert photo_kwargs["chat_id"] == 123
            assert photo_kwargs["photo_bytes"] == b"dummy_jpeg_content_12345"
            assert "Hussain Sagar" in photo_kwargs.get("caption", "")

    asyncio.run(run())


def test_telegram_plain_text_waterbody_lookup(mock_telegram_client, db_session):
    """Test plain text query automatically routes to waterbody lookup."""
    import uuid
    from app.db.models.water_body import WaterBody

    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Vembanad Lake",
        normalized_name="vembanad lake",
        source="osm",
        country="India",
        state_province="Kerala",
    )
    db_session.add(wb)
    db_session.commit()

    async def run():
        handler = TelegramCommandHandler(mock_telegram_client, db_factory=lambda: db_session)
        # Send plain text name without /waterbody slash
        msg = make_msg(123, "Vembanad Lake")
        await handler.handle_message(msg)

        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "VEMBANAD LAKE" in reply
        assert "Location" in reply

    asyncio.run(run())


def test_telegram_ai_with_waterbody_context(mock_telegram_client, db_session):
    """Test /ai detects water body mentions in prompt and supplies water_body_id context."""
    import uuid
    from app.db.models.water_body import WaterBody

    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Loktak Lake",
        normalized_name="loktak lake",
        source="osm",
    )
    db_session.add(wb)
    db_session.commit()

    async def run():
        mock_ai = MagicMock()
        mock_response = MagicMock()
        mock_response.answer = "Loktak Lake water clarity is moderate."
        mock_ai.generate_analysis_response = MagicMock(return_value=mock_response)
        handler = TelegramCommandHandler(mock_telegram_client, ai_service=mock_ai, db_factory=lambda: db_session)

        msg = make_msg(123, "/ai What is the current condition of Loktak Lake?")
        await handler.handle_message(msg)

        # AI service should be called with water_body_id
        mock_ai.generate_analysis_response.assert_called_once()
        call_kwargs = mock_ai.generate_analysis_response.call_args[1]
        assert call_kwargs["water_body_id"] == wb.id

        mock_telegram_client.send_message.assert_called_once()
        reply = mock_telegram_client.send_message.call_args[0][1]
        assert "Loktak Lake water clarity is moderate." in reply

    asyncio.run(run())

