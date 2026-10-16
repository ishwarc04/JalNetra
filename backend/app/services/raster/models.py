"""
Raster models for JalNetra map & raster visualization services.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class GeoBounds(BaseModel):
    """Geographic bounding box in EPSG:4326 (WGS84)."""
    west: float = Field(..., description="Minimum longitude (West)")
    south: float = Field(..., description="Minimum latitude (South)")
    east: float = Field(..., description="Maximum longitude (East)")
    north: float = Field(..., description="Maximum latitude (North)")


class AssetMetadata(BaseModel):
    """Metadata for a single raster asset."""
    asset_key: str
    asset_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    crs: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    resolution_meters: Optional[float] = None
    nodata: Optional[float] = None
    is_downloaded: bool = False


class SceneRasterMetadataResponse(BaseModel):
    """Metadata response for a satellite scene's raster assets and visualization bounds."""
    scene_id: str
    external_scene_id: str
    provider: str
    collection: str
    sensing_start: str
    cloud_cover_percent: Optional[float] = None
    crs: Optional[str] = None
    geographic_bounds: Optional[GeoBounds] = None
    native_bounds: Optional[dict] = None
    available_assets: List[AssetMetadata] = []
    rgb_available: bool = False
    rgb_cached: bool = False
    image_url: Optional[str] = None


class RGBVisualizationResponse(BaseModel):
    """Response containing RGB visualization metadata and display bounds."""
    scene_id: str
    external_scene_id: str
    water_body_id: Optional[str] = None
    is_focused: bool = False
    crs: str = "EPSG:4326"
    source_crs: Optional[str] = "EPSG:32643"
    resolution_m: Optional[float] = 10.0
    bands: List[str] = ["B04", "B03", "B02"]
    sensing_date: Optional[str] = None
    bounds: GeoBounds
    width: int
    height: int
    image_url: str
    cached: bool
    description: str = "Sentinel-2 L2A True-Color (B04/Red, B03/Green, B02/Blue) percentile-stretched visualization"
