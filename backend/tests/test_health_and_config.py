import pytest
from starlette.testclient import TestClient
from app.core.config import settings
from app.core.paths import get_repo_root, resolve_path, ensure_data_directories
from app.db.database import SessionLocal
from sqlalchemy import text


def test_config_loading():
    """Verify configuration loads with correct defaults."""
    assert settings.APP_NAME == "JalNetra API"
    assert settings.APP_VERSION == "2.0.0"
    assert "sqlite:///" in settings.resolved_database_url
    assert settings.resolved_data_dir.is_absolute()
    assert "http://localhost:5173" in settings.cors_origins


def test_paths_utility(tmp_path):
    """Verify path resolution and data directory creation."""
    repo_root = get_repo_root()
    assert repo_root.exists()
    assert (repo_root / "backend").exists()

    # Relative path resolution
    resolved = resolve_path("data/test")
    assert resolved == (repo_root / "data/test").resolve()

    # Directory creation
    test_data = tmp_path / "data"
    subdirs = ensure_data_directories(test_data)
    assert len(subdirs) == 8
    for d in subdirs:
        assert d.exists()
        assert d.is_dir()


def test_database_connection():
    """Verify database engine connects cleanly and executes query."""
    with SessionLocal() as session:
        result = session.execute(text("SELECT 1")).scalar()
        assert result == 1


def test_root_health_endpoint(client: TestClient):
    """Verify GET /health returns expected status and info."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == settings.APP_NAME
    assert data["version"] == settings.APP_VERSION


def test_api_v1_health_endpoint(client: TestClient):
    """Verify GET /api/v1/health returns expected status and info."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == settings.APP_NAME
    assert data["version"] == settings.APP_VERSION


def test_openapi_docs(client: TestClient):
    """Verify Swagger OpenAPI docs are accessible."""
    response = client.get("/docs")
    assert response.status_code == 200
    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == settings.APP_NAME


def test_consistent_error_handling(client: TestClient):
    """Verify 404 and API error response format consistency."""
    response = client.get("/api/v1/nonexistent-endpoint")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "HTTP_404"
