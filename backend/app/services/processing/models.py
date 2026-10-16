"""
Pydantic data models for Sentinel-2 preprocessing: cloud masking and water detection (Phase 5).
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from app.services.raster.models import GeoBounds


class CloudMaskMetadata(BaseModel):
    """Metadata regarding Scene Classification Layer (SCL) cloud/shadow masking."""
    source_layer: str = "SCL"
    masked_classes: List[int] = Field(
        default=[0, 1, 3, 8, 9, 10, 11],
        description="SCL classes considered invalid/cloud/shadow/snow: 0=NoData, 1=Defective, 3=Shadow, 8=Cloud Med, 9=Cloud High, 10=Cirrus, 11=Snow",
    )
    total_pixels: int
    valid_pixels: int
    cloud_shadow_pixels: int
    valid_pixel_percentage: float
    cloud_shadow_percentage: float


class WaterDetectionMetadata(BaseModel):
    """Metadata regarding deterministic spectral water segmentation."""
    method: str = "Normalized Difference Spectral Segmentation (Green/NIR)"
    threshold: float = Field(default=0.0, description="Spectral segmentation threshold: water if (B03 - B08)/(B03 + B08) > threshold")
    source_bands: List[str] = Field(default=["B03", "B08"], description="Bands used for water detection")
    total_pixels: int
    valid_pixels_evaluated: int
    water_pixels: int
    water_extent_percentage_of_valid: float
    water_extent_percentage_of_total: float
    estimated_water_area_sq_km: Optional[float] = None


class ProcessingStatusResponse(BaseModel):
    """Overall processing status for a Sentinel-2 scene."""
    scene_id: str
    external_scene_id: str
    status: str = Field(..., description="'ready', 'unprocessed', or 'missing_assets'")
    cloud_mask_available: bool = False
    water_mask_available: bool = False
    cloud_mask: Optional[CloudMaskMetadata] = None
    water_detection: Optional[WaterDetectionMetadata] = None
    source_bands_present: List[str] = []
    missing_required_bands: List[str] = []
    created_at: Optional[str] = None
    cloud_mask_image_url: Optional[str] = None
    water_mask_image_url: Optional[str] = None


class MaskVisualizationResponse(BaseModel):
    """Response containing map display bounds and image URL for a processed mask overlay."""
    scene_id: str
    mask_type: str = Field(..., description="'cloud_mask' or 'water_mask'")
    crs: str = "EPSG:4326"
    bounds: GeoBounds
    width: int
    height: int
    image_url: str
    cached: bool
    description: str
