"""
Sentinel-2 Preprocessing Package: SCL Cloud Masking and Deterministic Spectral Water Detection.
"""
from app.services.processing.service import ProcessingService
from app.services.processing.cloud_mask import CloudMaskGenerator
from app.services.processing.water_detection import WaterDetector, DEFAULT_WATER_THRESHOLD
from app.services.processing.models import (
    CloudMaskMetadata,
    WaterDetectionMetadata,
    ProcessingStatusResponse,
    MaskVisualizationResponse,
)

__all__ = [
    "ProcessingService",
    "CloudMaskGenerator",
    "WaterDetector",
    "DEFAULT_WATER_THRESHOLD",
    "CloudMaskMetadata",
    "WaterDetectionMetadata",
    "ProcessingStatusResponse",
    "MaskVisualizationResponse",
]
