from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models.cache_entry import CacheEntry
from app.schemas.cache import CacheEntryCreate


class CacheRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_key(self, cache_key: str) -> Optional[CacheEntry]:
        entry = self.db.execute(
            select(CacheEntry).where(CacheEntry.cache_key == cache_key)
        ).scalar_one_or_none()
        if entry:
            entry.last_accessed_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(entry)
        return entry

    def create(self, data: CacheEntryCreate) -> CacheEntry:
        entry = CacheEntry(**data.model_dump())
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def delete_by_key(self, cache_key: str) -> bool:
        entry = self.db.execute(
            select(CacheEntry).where(CacheEntry.cache_key == cache_key)
        ).scalar_one_or_none()
        if not entry:
            return False
        self.db.delete(entry)
        self.db.commit()
        return True
