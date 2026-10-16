import hashlib
import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator
from app.schemas.water_body import WaterBodyRead


def compute_geometry_hash_from_dict(geom: Optional[Dict[str, Any]]) -> Optional[str]:
    if not geom:
        return None
    try:
        canonical = json.dumps(geom, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except Exception:
        return None


class WaterBodyDiscoveryResult(BaseModel):
    provider: str = Field(..., max_length=50, description="Provider identifier, e.g., 'osm'")
    source_id: str = Field(..., max_length=100, description="Provider's external ID, e.g., 'relation/12345'")
    name: str = Field(..., min_length=1, max_length=255, description="Primary name of the water body")
    water_body_type: Optional[str] = Field(None, max_length=50, description="lake, reservoir, river, etc.")
    country: Optional[str] = Field(None, max_length=100)
    state_province: Optional[str] = Field(None, max_length=100)
    district: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None

    # Geometry fields
    geometry_geojson: Optional[str] = Field(None, description="Serialized GeoJSON geometry string")
    geometry_hash: Optional[str] = Field(None, max_length=64)

    # Bounding Box (min_lat, min_lon, max_lat, max_lon)
    min_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    min_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)
    max_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    max_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)

    # Centroid
    centroid_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    centroid_lon: Optional[float] = Field(None, ge=-180.0, le=180.0)

    # Area estimation in square kilometers
    area_sq_km: Optional[float] = Field(None, ge=0.0)

    # Raw provider metadata for reference
    source_metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_bounds_and_hash(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name cannot be empty")

        if self.min_lat is not None and self.max_lat is not None:
            if self.min_lat > self.max_lat:
                raise ValueError("min_lat cannot exceed max_lat")

        if self.min_lon is not None and self.max_lon is not None:
            if self.min_lon > self.max_lon:
                raise ValueError("min_lon cannot exceed max_lon")

        # Derive geometry hash if not provided and geometry_geojson exists
        if not self.geometry_hash and self.geometry_geojson:
            try:
                parsed = json.loads(self.geometry_geojson)
                self.geometry_hash = compute_geometry_hash_from_dict(parsed)
            except Exception:
                pass

        return self


class DiscoverySearchResponse(BaseModel):
    query: str
    provider: str
    results: List[WaterBodyDiscoveryResult]


class ProviderStatus(BaseModel):
    name: str
    enabled: bool
    status: str
    description: Optional[str] = None


class ProviderListResponse(BaseModel):
    providers: List[ProviderStatus]


class GeocodedLocation(BaseModel):
    display_name: str
    latitude: float
    longitude: float
    type: Optional[str] = None
    boundingbox: Optional[List[float]] = None


class LocationSearchResponse(BaseModel):
    query: str
    results: List[GeocodedLocation]


class SearchCenter(BaseModel):
    latitude: float
    longitude: float


class SearchBoundingBox(BaseModel):
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


class AreaDiscoveryResponse(BaseModel):
    query_location: Optional[str] = None
    center: SearchCenter
    radius_km: float
    bounding_box: SearchBoundingBox
    total_discovered: int
    results: List[WaterBodyDiscoveryResult]


class BatchImportRequest(BaseModel):
    water_bodies: List[WaterBodyDiscoveryResult] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of discovered water bodies to import",
    )
    water_body_ids: Optional[List[str]] = Field(
        None,
        description="Optional list of source IDs corresponding to the items",
    )


class BatchImportItemResult(BaseModel):
    source_id: str
    name: str
    status: str = Field(..., description="'imported' | 'already_registered' | 'failed'")
    water_body: Optional[WaterBodyRead] = None
    error: Optional[str] = None


class BatchImportResponse(BaseModel):
    total_requested: int
    imported_count: int
    already_existed_count: int
    failed_count: int
    results: List[BatchImportItemResult]


