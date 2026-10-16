import hashlib
import json
import re
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator, ConfigDict


def normalize_string(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    val = val.strip()
    return val if val else None


def compute_geometry_hash(geojson_str: Optional[str]) -> Optional[str]:
    if not geojson_str:
        return None
    try:
        # Parse and re-dump with sorted keys for consistent hashing
        parsed = json.loads(geojson_str)
        canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except Exception:
        # Fallback to string hash if not valid json
        return hashlib.sha256(geojson_str.strip().encode("utf-8")).hexdigest()


class WaterBodyBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Name of the water body")
    country: Optional[str] = Field(None, max_length=100)
    state_province: Optional[str] = Field(None, max_length=100)
    district: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    source: str = Field("manual", max_length=50, description="Catalog source or origin")
    source_id: Optional[str] = Field(None, max_length=100, description="External record identifier")
    water_body_type: Optional[str] = Field(None, max_length=50, description="lake, reservoir, pond, etc.")
    description: Optional[str] = None

    geometry_geojson: Optional[str] = None
    min_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    min_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)
    max_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    max_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)

    centroid_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    centroid_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)
    area_sq_km: Optional[float] = Field(None, ge=0.0)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_bounds_and_names(self):
        # Validate latitude bounds
        if self.min_lat is not None and self.max_lat is not None:
            if self.min_lat > self.max_lat:
                raise ValueError("min_lat cannot be greater than max_lat")

        # Validate longitude bounds
        if self.min_lon is not None and self.max_lon is not None:
            if self.min_lon > self.max_lon:
                raise ValueError("min_lon cannot be greater than max_lon")

        # Strip strings
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name cannot be empty or whitespace only")

        if self.country:
            self.country = self.country.strip()
        if self.state_province:
            self.state_province = self.state_province.strip()
        if self.district:
            self.district = self.district.strip()
        if self.city:
            self.city = self.city.strip()
        if self.source:
            self.source = self.source.strip()
        if self.source_id:
            self.source_id = self.source_id.strip()

        return self


class WaterBodyCreate(WaterBodyBase):
    pass


class WaterBodyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    state_province: Optional[str] = Field(None, max_length=100)
    district: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    source: Optional[str] = Field(None, max_length=50)
    source_id: Optional[str] = Field(None, max_length=100)
    water_body_type: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None

    geometry_geojson: Optional[str] = None
    min_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    min_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)
    max_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    max_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)

    centroid_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    centroid_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)
    area_sq_km: Optional[float] = Field(None, ge=0.0)
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("name cannot be empty or whitespace only")
        if self.min_lat is not None and self.max_lat is not None:
            if self.min_lat > self.max_lat:
                raise ValueError("min_lat cannot be greater than max_lat")
        if self.min_lon is not None and self.max_lon is not None:
            if self.min_lon > self.max_lon:
                raise ValueError("min_lon cannot be greater than max_lon")
        return self


class WaterBodyRead(WaterBodyBase):
    id: str
    normalized_name: str
    geometry_hash: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)



class WaterBodyListResponse(BaseModel):
    items: List[WaterBodyRead]
    total: int
    limit: int
    offset: int
