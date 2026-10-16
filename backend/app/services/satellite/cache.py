import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.repositories.cache_repository import CacheRepository
from app.services.storage_service import LocalStorageService, storage_service

logger = logging.getLogger("jalnetra.satellite.cache")


class SatelliteCacheService:
    """
    Manages caching of STAC query responses using CacheEntry and LocalStorageService.
    Results are stored as JSON files under data/cache/{cache_key}.json.
    """

    def __init__(
        self,
        db: Session,
        storage: Optional[LocalStorageService] = None,
        default_ttl_seconds: Optional[int] = None,
    ):
        self.db = db
        self.repo = CacheRepository(db)
        self.storage = storage or storage_service
        self.ttl = default_ttl_seconds or settings.SATELLITE_CACHE_TTL_SECONDS

    @staticmethod
    def build_cache_key(
        provider: str,
        collection: str,
        water_body_id: str,
        start_date: Optional[str],
        end_date: Optional[str],
        max_cloud_cover: float,
        limit: int,
    ) -> str:
        s_str = start_date or "all"
        e_str = end_date or "all"
        raw_key = f"stac-scenes:{provider}:{collection}:{water_body_id}:{s_str}:{e_str}:{max_cloud_cover}:{limit}"
        if len(raw_key) > 200:
            h = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:20]
            return f"stac-scenes:{provider}:{collection}:{water_body_id}:{h}"
        return raw_key

    def get(self, cache_key: str) -> Optional[List[Dict[str, Any]]]:
        entry = self.repo.get_by_key(cache_key)
        if not entry:
            return None

        now = datetime.now(timezone.utc)
        if entry.expires_at:
            exp = entry.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if now > exp:
                logger.info("Satellite STAC cache '%s' expired", cache_key)
                self.delete(cache_key)
                return None

        if not entry.local_path or not self.storage.exists(entry.local_path):
            return None

        try:
            file_bytes = self.storage.read_bytes(entry.local_path)
            data = json.loads(file_bytes.decode("utf-8"))
            return data if isinstance(data, list) else None
        except Exception as exc:
            logger.warning("Failed to decode STAC cache for key '%s': %s", cache_key, exc)
            return None

    def set(
        self,
        cache_key: str,
        provider: str,
        source_id: str,
        scenes_data: List[Dict[str, Any]],
    ) -> None:
        try:
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=self.ttl)
            json_bytes = json.dumps(scenes_data, indent=2, default=str).encode("utf-8")

            safe_name = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24]
            rel_path = f"cache/stac_{safe_name}.json"

            self.storage.save_bytes(rel_path, json_bytes)
            file_size = len(json_bytes)
            sha256_hash = hashlib.sha256(json_bytes).hexdigest()

            existing = self.repo.get_by_key(cache_key)
            if existing:
                existing.local_path = rel_path
                existing.file_size_bytes = file_size
                existing.sha256 = sha256_hash
                existing.expires_at = expires_at
                existing.last_accessed_at = now
                existing.status = "valid"
                self.db.commit()
            else:
                from app.schemas.cache import CacheEntryCreate

                dto = CacheEntryCreate(
                    cache_key=cache_key,
                    cache_type="stac_search_scenes",
                    source=provider,
                    source_identifier=source_id[:255],
                    local_path=rel_path,
                    file_size_bytes=file_size,
                    sha256=sha256_hash,
                    status="valid",
                    expires_at=expires_at,
                )
                self.repo.create(dto)
        except Exception as exc:
            logger.error("Failed to write satellite cache for '%s': %s", cache_key, exc)

    def delete(self, cache_key: str) -> None:
        entry = self.repo.get_by_key(cache_key)
        if entry:
            if entry.local_path:
                try:
                    self.storage.delete(entry.local_path)
                except Exception:
                    pass
            self.repo.delete_by_key(cache_key)
