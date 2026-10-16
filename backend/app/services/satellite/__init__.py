"""Satellite Subsystem Package"""
from app.services.satellite.base import SatelliteProvider
from app.services.satellite.models import (
    NormalizedScene,
    NormalizedAsset,
    SceneSearchQuery,
    SceneSearchResponse,
    AcquireAssetsRequest,
    AssetAcquisitionStatus,
    SceneAcquisitionResponse,
)
from app.services.satellite.service import SatelliteService, SatelliteServiceError
from app.services.satellite.observation_service import SatelliteObservationService, ObservationServiceError
from app.services.satellite.providers.stac import EarthSearchSTACProvider

__all__ = [
    "SatelliteProvider",
    "NormalizedScene",
    "NormalizedAsset",
    "SceneSearchQuery",
    "SceneSearchResponse",
    "AcquireAssetsRequest",
    "AssetAcquisitionStatus",
    "SceneAcquisitionResponse",
    "SatelliteService",
    "SatelliteServiceError",
    "SatelliteObservationService",
    "ObservationServiceError",
    "EarthSearchSTACProvider",
]
