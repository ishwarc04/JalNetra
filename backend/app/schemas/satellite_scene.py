from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, model_validator, ConfigDict


class SatelliteSceneBase(BaseModel):
    provider: str = Field(..., max_length=50)
    collection: str = Field(..., max_length=100)
    external_scene_id: str = Field(..., max_length=255)
    product_id: Optional[str] = Field(None, max_length=255)

    sensing_start: datetime
    sensing_end: Optional[datetime] = None
    cloud_cover_percent: Optional[float] = Field(None, ge=0.0, le=100.0)
    processing_level: Optional[str] = Field(None, max_length=50)

    bbox_min_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    bbox_min_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)
    bbox_max_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    bbox_max_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)

    footprint_geojson: Optional[str] = None
    metadata_json: Optional[str] = None
    status: str = Field("discovered", max_length=50)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.bbox_min_lat is not None and self.bbox_max_lat is not None:
            if self.bbox_min_lat > self.bbox_max_lat:
                raise ValueError("bbox_min_lat cannot exceed bbox_max_lat")
        if self.bbox_min_lon is not None and self.bbox_max_lon is not None:
            if self.bbox_min_lon > self.bbox_max_lon:
                raise ValueError("bbox_min_lon cannot exceed bbox_max_lon")
        return self


class SatelliteSceneCreate(SatelliteSceneBase):
    pass


class SatelliteSceneRead(SatelliteSceneBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)



class SatelliteSceneListResponse(BaseModel):
    items: List[SatelliteSceneRead]
    total: int
    limit: int
    offset: int
