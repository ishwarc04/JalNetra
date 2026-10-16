from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import settings
from app.db.models.cache_entry import CacheEntry
from app.db.repositories.cache_repository import CacheRepository
from app.services.storage_service import LocalStorageService, storage_service

logger = logging.getLogger("jalnetra.discovery.cache")


class DiscoveryCacheService:
    """
    Manages caching of discovery provider queries using CacheEntry and LocalStorageService.
    Responses are stored as JSON files under data/cache/{cache_key}.json to avoid SQLite BLOB storage.
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
        self.ttl = default_ttl_seconds or settings.WATERBODY_DISCOVERY_CACHE_TTL_SECONDS

    @staticmethod
    def build_cache_key(provider: str, query: str, limit: int) -> str:
        """
        Creates a deterministic normalized cache key.
        e.g., 'waterbody-discovery:osm:chilika lake:10'
        """
        normalized_query = " ".join(query.strip().lower().split())
        raw_key = f"waterbody-discovery:{provider.strip().lower()}:{normalized_query}:{limit}"
        # If key length exceeds 200 chars, hash the query part to fit DB index safely
        if len(raw_key) > 200:
            query_hash = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()[:16]
            return f"waterbody-discovery:{provider.strip().lower()}:{query_hash}:{limit}"
        return raw_key

    def get(self, cache_key: str) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieves cached discovery results if entry exists and is not expired.
        """
        entry = self.repo.get_by_key(cache_key)
        if not entry:
            return None

        # Check expiration
        now = datetime.now(timezone.utc)
        if entry.expires_at:
            # Ensure timezone awareness comparison
            expires_at = entry.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if now > expires_at:
                logger.info("Cache entry '%s' expired at %s", cache_key, expires_at)
                self.delete(cache_key)
                return None

        # Read JSON file from storage
        if not entry.local_path or not self.storage.exists(entry.local_path):
            logger.warning("Cache entry exists in DB but file '%s' missing on disk", entry.local_path)
            return None

        try:
            file_bytes = self.storage.read_bytes(entry.local_path)
            data = json.loads(file_bytes.decode("utf-8"))
            if isinstance(data, list):
                return data
            return None
        except Exception as exc:
            logger.warning("Failed to decode cached data for key '%s': %s", cache_key, exc)
            return None

    def set(
        self,
        cache_key: str,
        provider: str,
        query: str,
        results: List[Dict[str, Any]],
    ) -> None:
        """
        Saves discovery results to file storage and registers in CacheEntry.
        """
        try:
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=self.ttl)
            json_bytes = json.dumps(results, indent=2, ensure_ascii=False).encode("utf-8")

            # Determine safe relative cache path: e.g. cache/{cache_key_hash}.json
            safe_name = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24]
            rel_path = f"cache/{safe_name}.json"

            saved_path = self.storage.save_bytes(rel_path, json_bytes)
            file_size = len(json_bytes)
            sha256_hash = hashlib.sha256(json_bytes).hexdigest()

            # Existing entry check
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
                    cache_type="waterbody_discovery",
                    source=provider,
                    source_identifier=query[:255],
                    local_path=rel_path,
                    file_size_bytes=file_size,
                    sha256=sha256_hash,
                    status="valid",
                    expires_at=expires_at,
                )
                self.repo.create(dto)

        except Exception as exc:
            logger.error("Failed to write discovery cache for key '%s': %s", cache_key, exc)

    def delete(self, cache_key: str) -> None:
        entry = self.repo.get_by_key(cache_key)
        if entry:
            if entry.local_path:
                try:
                    self.storage.delete(entry.local_path)
                except Exception:
                    pass
            self.repo.delete_by_key(cache_key)
