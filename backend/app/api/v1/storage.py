from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.storage.reset_service import reset_service
from app.schemas.storage import (
    StorageStatusResponse,
    StorageResetResponse,
)

router = APIRouter(prefix="/storage", tags=["Storage & Maintenance"])


@router.get(
    "/status",
    response_model=StorageStatusResponse,
    summary="Storage and database status",
    description="Returns full audit of database records, local storage sizes, directory status, and orphan detections.",
)
def get_storage_status(db: Session = Depends(get_db)) -> StorageStatusResponse:
    return reset_service.collect_storage_status(db)


@router.post(
    "/clear/cache",
    response_model=StorageResetResponse,
    summary="Clear cache entries",
    description="Deletes all database cache records and removes temporary cache files from disk.",
)
def clear_cache(db: Session = Depends(get_db)) -> StorageResetResponse:
    return reset_service.clear_cache(db)


@router.post(
    "/clear/processed",
    response_model=StorageResetResponse,
    summary="Clear processed imagery data",
    description="Deletes all analysis run records and generated mask/image outputs from disk.",
)
def clear_processed_data(db: Session = Depends(get_db)) -> StorageResetResponse:
    return reset_service.clear_processed_data(db)


@router.post(
    "/clear/satellite",
    response_model=StorageResetResponse,
    summary="Clear satellite scenes and imagery",
    description="Deletes all satellite scene and asset records, and deletes raw GeoTIFF files from disk.",
)
def clear_satellite_data(db: Session = Depends(get_db)) -> StorageResetResponse:
    return reset_service.clear_satellite_data(db)


@router.post(
    "/reset",
    response_model=StorageResetResponse,
    summary="Reset all project data",
    description="Completely purges all application database records and all local storage files (scenes, processed, cache, exports). Schema and alembic versions remain intact.",
)
def reset_project_data(db: Session = Depends(get_db)) -> StorageResetResponse:
    return reset_service.reset_all_data(db)
