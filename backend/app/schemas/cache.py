from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class CacheEntryBase(BaseModel):
    cache_key: str = Field(..., max_length=255)
    cache_type: str = Field(..., max_length=50)
    source: Optional[str] = Field(None, max_length=50)
    source_identifier: Optional[str] = Field(None, max_length=255)
    local_path: Optional[str] = Field(None, max_length=1024)
    file_size_bytes: Optional[int] = Field(None, ge=0)
    sha256: Optional[str] = Field(None, max_length=64)
    status: str = Field("valid", max_length=50)
    expires_at: Optional[datetime] = None
    metadata_json: Optional[str] = None


class CacheEntryCreate(CacheEntryBase):
    pass


class CacheEntryRead(CacheEntryBase):
    id: str
    created_at: datetime
    last_accessed_at: datetime

    model_config = ConfigDict(from_attributes=True)



class CacheEntryListResponse(BaseModel):
    items: List[CacheEntryRead]
    total: int
