from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.core.paths import get_repo_root, resolve_path


class Settings(BaseSettings):
    APP_NAME: str = "JalNetra API"
    APP_VERSION: str = "2.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database & Storage
    DATABASE_URL: str = "sqlite:///./data/database/jalnetra.db"
    DATA_DIR: str = "./data"

    # CORS
    FRONTEND_URL: str = "http://localhost:5173"

    # Placeholders for future integrations
    SENTINEL_CLIENT_ID: str = ""
    SENTINEL_CLIENT_SECRET: str = ""
    GEE_PROJECT_ID: str = ""

    # AI Assistant (OpenAI)
    AI_ENABLED: bool = True
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    AI_MAX_OUTPUT_TOKENS: int = 800

    # Telegram Bot
    TELEGRAM_ENABLED: bool = True
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_BOT_USERNAME: str = "jalNetra_Helperbot"
    TELEGRAM_ALLOWED_CHAT_IDS: str = ""  # Comma-separated or empty for all

    # Water Body Discovery (Phase 2)
    WATERBODY_DISCOVERY_ENABLED: bool = True
    WATERBODY_DISCOVERY_PROVIDER: str = "osm"
    WATERBODY_DISCOVERY_TIMEOUT_SECONDS: float = 15.0
    WATERBODY_DISCOVERY_CACHE_TTL_SECONDS: int = 86400
    WATERBODY_DISCOVERY_USER_AGENT: str = "JalNetra/2.0 (Geospatial Water Resource Monitoring; contact@jalnetra.local)"

    # Satellite Acquisition (Phase 3)
    SATELLITE_PROVIDER: str = "earth_search"
    SATELLITE_STAC_URL: str = "https://earth-search.aws.element84.com/v1"
    SATELLITE_COLLECTION: str = "sentinel-2-c1-l2a"
    SATELLITE_REQUEST_TIMEOUT_SECONDS: float = 60.0
    SATELLITE_CACHE_TTL_SECONDS: int = 86400

    # Map & Visualization Focus Settings
    WATER_BODY_MAP_PADDING_PERCENT: float = 10.0

    model_config = SettingsConfigDict(
        # Keep configuration independent of the process working directory.
        # Repository settings override the optional backend-local file.
        env_file=(get_repo_root() / "backend" / ".env", get_repo_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def resolved_data_dir(self) -> Path:
        return resolve_path(self.DATA_DIR)

    @property
    def resolved_database_url(self) -> str:
        """
        If using SQLite with a relative path (sqlite:///./path),
        resolve it to an absolute path based on repo root so connection works
        regardless of CWD.
        """
        prefix = "sqlite:///"
        if self.DATABASE_URL.startswith(prefix):
            raw_path = self.DATABASE_URL[len(prefix):]
            # If path is not in-memory
            if raw_path and raw_path != ":memory:":
                abs_path = resolve_path(raw_path)
                # Ensure parent dir exists
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                # Form valid SQLite URL for Windows/POSIX (using forward slashes)
                return f"sqlite:///{abs_path.as_posix()}"
        return self.DATABASE_URL

    @property
    def cors_origins(self) -> List[str]:
        origins = [self.FRONTEND_URL.strip()] if self.FRONTEND_URL else []
        return [o for o in origins if o]


settings = Settings()
