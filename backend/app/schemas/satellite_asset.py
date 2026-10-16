from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class SatelliteAssetBase(BaseModel):
    scene_id: str
    asset_key: str = Field(..., max_length=100)
    asset_type: Optional[str] = Field(None, max_length=50)
    remote_url: Optional[str] = Field(None, max_length=1024)
    local_path: Optional[str] = Field(None, max_length=1024)
    mime_type: Optional[str] = Field(None, max_length=100)
    file_size_bytes: Optional[int] = Field(None, ge=0)
    sha256: Optional[str] = Field(None, max_length=64)
    status: str = Field("remote", max_length=50)


class SatelliteAssetCreate(SatelliteAssetBase):
    pass


class SatelliteAssetRead(SatelliteAssetBase):
    id: str
    created_at: datetime
    updated_at: datetime
    downloaded_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)



class SatelliteAssetListResponse(BaseModel):
    items: List[SatelliteAssetRead]
    total: int
