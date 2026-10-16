import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.models.water_body import WaterBody
from app.db.models.satellite_observation import SatelliteObservation
from app.services.ai import AIService, AIServiceError, OpenAIClientWrapper
from app.services.ai.client import AuthenticationError, RateLimitError, APITimeoutError


@pytest.fixture
def mock_water_body_with_obs(db_session):
    """Creates a test water body and observation in DB."""
    import uuid
    from datetime import datetime, timezone

    wb = WaterBody(
        id=str(uuid.uuid4()),
        name="Test Analysis Lake",
        normalized_name="test analysis lake",
        source="osm",
        water_body_type="lake",
        country="India",
        state_province="Maharashtra",
        district="Aurangabad",
        city="Aurangabad",
        area_sq_km=0.25,
        centroid_lat=19.9,
        centroid_lon=75.3,
        min_lat=19.89,
        max_lat=19.91,
        min_lon=75.29,
        max_lon=75.31,
    )
    db_session.add(wb)
    db_session.commit()

    obs = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb.id,
        external_scene_id="S2C_TEST_20261010",
        provider="earth_search",
        sensing_date=datetime(2026, 10, 10, 5, 30, tzinfo=timezone.utc),
        cloud_cover_percent=0.5,
        derived_water_area_sq_km=0.24,
        local_visual_path="test.png",
    )
    db_session.add(obs)
    db_session.commit()
    db_session.refresh(wb)
    db_session.refresh(obs)
    return wb, obs


def test_ai_status_endpoint(client: TestClient):
    """GET /api/v1/ai/status should report status without exposing keys."""
    resp = client.get("/api/v1/ai/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "configured" in data
    assert "model" in data
    assert "provider" in data
    assert data["provider"] == "openai"
    # Security: Ensure key is not in JSON
    assert "api_key" not in data
    assert "key" not in data


def test_ai_service_context_building(db_session, mock_water_body_with_obs):
    """Verify context object contains structured water body & observation metadata."""
    wb, obs = mock_water_body_with_obs
    service = AIService(db=db_session)

    ctx = service.build_water_body_context(wb.id, obs.id)
    assert ctx["water_body"]["name"] == "Test Analysis Lake"
    assert ctx["water_body"]["area_km2"] == 0.25
    assert "selected_observation" in ctx
    assert ctx["selected_observation"]["date"] == "2026-10-10"
    assert ctx["selected_observation"]["apparent_extent_km2"] == 0.24
    assert len(ctx["temporal_timeline"]) == 1


def test_ai_data_isolation(db_session, mock_water_body_with_obs):
    """Verify that different water bodies have strictly isolated contexts."""
    wb1, obs1 = mock_water_body_with_obs
    import uuid
    wb2 = WaterBody(
        id=str(uuid.uuid4()),
        name="Isolated Reservoir 2",
        normalized_name="isolated reservoir 2",
        source="osm",
        area_sq_km=1.5,
    )
    db_session.add(wb2)
    db_session.commit()

    service = AIService(db=db_session)
    ctx1 = service.build_water_body_context(wb1.id)
    ctx2 = service.build_water_body_context(wb2.id)

    assert ctx1["water_body"]["name"] == "Test Analysis Lake"
    assert ctx2["water_body"]["name"] == "Isolated Reservoir 2"
    assert "Test Analysis Lake" not in str(ctx2)
    assert "Isolated Reservoir 2" not in str(ctx1)


def test_ai_analyze_endpoint_mocked(client: TestClient, db_session, mock_water_body_with_obs):
    """Test /api/v1/ai/analyze returns AI response with mocked OpenAI SDK."""
    wb, obs = mock_water_body_with_obs

    mock_chat_completion = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = (
        "1. Observed: The lake shows stable water extent of ~0.24 km² with low cloud cover.\n"
        "2. Indication: Clear surface conditions.\n"
        "3. Quality: High confidence observation."
    )
    mock_chat_completion.choices = [mock_choice]

    with patch.object(settings, "OPENAI_API_KEY", "sk-mock-test-key-12345"):
        with patch("openai.resources.chat.completions.Completions.create", return_value=mock_chat_completion):
            resp = client.post(
                "/api/v1/ai/analyze",
                json={
                    "water_body_id": wb.id,
                    "observation_id": obs.id,
                    "question": "Explain current water condition",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "answer" in data
            assert "Observed" in data["answer"]
            assert data["water_body_name"] == "Test Analysis Lake"
            assert "disclaimer" in data


def test_ai_disabled_graceful_handling(client: TestClient, db_session, mock_water_body_with_obs):
    """When AI_ENABLED=false, endpoint returns 503 with friendly message."""
    wb, obs = mock_water_body_with_obs
    with patch.object(settings, "AI_ENABLED", False):
        resp = client.post(
            "/api/v1/ai/analyze",
            json={
                "water_body_id": wb.id,
                "question": "Explain water condition",
            },
        )
        assert resp.status_code == 503
        data = resp.json()
        assert "disabled" in data["error"]["message"].lower()


def test_ai_missing_key_graceful_handling(client: TestClient, db_session, mock_water_body_with_obs):
    """When OPENAI_API_KEY is empty, endpoint returns 503 with friendly message."""
    wb, obs = mock_water_body_with_obs
    with patch.object(settings, "AI_ENABLED", True):
        with patch.object(settings, "OPENAI_API_KEY", ""):
            resp = client.post(
                "/api/v1/ai/analyze",
                json={
                    "water_body_id": wb.id,
                    "question": "Explain water condition",
                },
            )
            assert resp.status_code == 503
            data = resp.json()
            assert "not configured" in data["error"]["message"].lower()


def test_ai_error_handling_timeout_and_ratelimit():
    """Verify OpenAI client wrapper converts SDK exceptions into friendly AIServiceError."""
    wrapper = OpenAIClientWrapper()

    with patch.object(settings, "AI_ENABLED", True):
        with patch.object(settings, "OPENAI_API_KEY", "sk-mock-key"):
            with patch("openai.resources.chat.completions.Completions.create", side_effect=RateLimitError(
                message="Rate limit exceeded", response=MagicMock(status_code=429), body={}
            )):
                with pytest.raises(AIServiceError) as exc_info:
                    wrapper.generate_chat_completion([{"role": "user", "content": "hello"}])
                assert exc_info.value.code == "AI_RATE_LIMIT"
                assert exc_info.value.status_code == 429
