from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class NormalizedAsset(BaseModel):
    asset_key: str = Field(..., description="Canonical asset key, e.g., B02, B03, B04, B08, B11, B12, SCL, thumbnail")
    asset_type: Optional[str] = Field(None, description="Type descriptor, e.g., raster_band, visual, mask, metadata")
    remote_url: str = Field(..., description="Public direct HTTP URL to download asset")
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class NormalizedScene(BaseModel):
    provider: str = Field(..., description="Satellite provider ID, e.g. 'earth_search'")
    collection: str = Field(..., description="STAC collection ID, e.g. 'sentinel-2-c1-l2a'")
    external_scene_id: str = Field(..., description="Unique STAC item ID, e.g. 'S2A_T45QTB_20240221T045850_L2A'")
    product_id: Optional[str] = None
    sensing_start: datetime
    sensing_end: Optional[datetime] = None
    cloud_cover_percent: Optional[float] = None
    processing_level: Optional[str] = Field("L2A", description="Processing level")
    bbox: Optional[List[float]] = Field(None, description="[min_lon, min_lat, max_lon, max_lat]")
    footprint_geojson: Optional[Dict[str, Any]] = None
    assets: Dict[str, NormalizedAsset] = Field(default_factory=dict)
    score: Optional[float] = Field(None, description="Deterministic ranking score (higher is better)")
    metadata_json: Optional[str] = None


class SceneSearchQuery(BaseModel):
    water_body_id: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    max_cloud_cover: float = Field(30.0, ge=0.0, le=100.0)
    limit: int = Field(10, ge=1, le=50)


class SceneSearchResponse(BaseModel):
    water_body_id: str
    provider: str
    collection: str
    results: List[NormalizedScene]


class AcquireAssetsRequest(BaseModel):
    assets: List[str] = Field(
        default=["B02", "B03", "B04", "B08", "B11", "B12", "SCL"],
        description="List of canonical asset keys to download",
    )


class AssetAcquisitionStatus(BaseModel):
    asset_key: str
    status: str  # downloaded, already_present, failed
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    local_path: Optional[str] = None
    error_message: Optional[str] = None


class SceneAcquisitionResponse(BaseModel):
    scene_id: str
    external_scene_id: str
    status: str  # completed, partial, failed
    downloaded_assets: int
    failed_assets: int
    already_present_assets: int
    assets: List[AssetAcquisitionStatus]
