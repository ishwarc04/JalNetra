from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

from app.schemas.water_body import (
    WaterBodyCreate,
    WaterBodyUpdate,
    WaterBodyRead,
    WaterBodyListResponse,
)
from app.schemas.satellite_scene import (
    SatelliteSceneCreate,
    SatelliteSceneRead,
    SatelliteSceneListResponse,
)
from app.schemas.satellite_asset import (
    SatelliteAssetCreate,
    SatelliteAssetRead,
    SatelliteAssetListResponse,
)
from app.schemas.analysis_run import (
    AnalysisRunCreate,
    AnalysisRunRead,
    AnalysisRunListResponse,
)
from app.schemas.cache import (
    CacheEntryCreate,
    CacheEntryRead,
    CacheEntryListResponse,
)


class HealthResponse(BaseModel):
    status: str = Field(..., description="Service status indicator", examples=["ok"])
    service: str = Field(..., description="Service name", examples=["JalNetra API"])
    version: str = Field(..., description="API semantic version", examples=["2.0.0"])


class ErrorDetail(BaseModel):
    code: str = Field(..., description="Standardized error code")
    message: str = Field(..., description="Human-readable error description")


class ErrorResponse(BaseModel):
    error: ErrorDetail


from app.schemas.storage import (
    StorageDirectoryStatus,
    StorageDatabaseCounts,
    StorageFilesystemSizes,
    StorageOrphansSummary,
    StorageStatusResponse,
    DatabaseResetSummary,
    FilesystemResetSummary,
    StorageResetResponse,
)


__all__ = [
    "HealthResponse",
    "ErrorDetail",
    "ErrorResponse",
    "StorageDirectoryStatus",
    "StorageDatabaseCounts",
    "StorageFilesystemSizes",
    "StorageOrphansSummary",
    "StorageStatusResponse",
    "DatabaseResetSummary",
    "FilesystemResetSummary",
    "StorageResetResponse",
    "WaterBodyCreate",
    "WaterBodyUpdate",
    "WaterBodyRead",
    "WaterBodyListResponse",
    "SatelliteSceneCreate",
    "SatelliteSceneRead",
    "SatelliteSceneListResponse",
    "SatelliteAssetCreate",
    "SatelliteAssetRead",
    "SatelliteAssetListResponse",
    "AnalysisRunCreate",
    "AnalysisRunRead",
    "AnalysisRunListResponse",
    "CacheEntryCreate",
    "CacheEntryRead",
    "CacheEntryListResponse",
]
