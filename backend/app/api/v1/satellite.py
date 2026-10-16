from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, Path, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.satellite import (
    SatelliteService,
    SceneSearchResponse,
    AcquireAssetsRequest,
    SceneAcquisitionResponse,
)

router = APIRouter(prefix="/satellite", tags=["Satellite"])


def get_satellite_service(db: Session = Depends(get_db)) -> SatelliteService:
    return SatelliteService(db)


@router.get(
    "/scenes/search",
    response_model=SceneSearchResponse,
    summary="Search Sentinel-2 satellite scenes for a water body or bounding box via STAC",
)
async def search_satellite_scenes(
    water_body_id: Optional[str] = Query(None, description="Target water body UUID"),
    bbox: Optional[str] = Query(None, description="Optional bounding box 'west,south,east,north'"),
    start_date: Optional[datetime] = Query(None, description="Start date (ISO8601)"),
    end_date: Optional[datetime] = Query(None, description="End date (ISO8601)"),
    max_cloud_cover: float = Query(30.0, ge=0.0, le=100.0, description="Max cloud cover %"),
    limit: int = Query(10, ge=1, le=50, description="Result limit (max 50)"),
    service: SatelliteService = Depends(get_satellite_service),
) -> SceneSearchResponse:
    from fastapi import HTTPException
    if not water_body_id and not bbox:
        raise HTTPException(status_code=400, detail="Either water_body_id or bbox must be provided")

    bbox_override = None
    if bbox:
        try:
            parts = [float(p.strip()) for p in bbox.split(",")]
            if len(parts) != 4:
                raise ValueError()
            bbox_override = parts
        except Exception:
            raise HTTPException(status_code=400, detail="Bounding box must be 'west,south,east,north'")

    return await service.search_scenes_for_water_body(
        water_body_id=water_body_id,
        start_date=start_date,
        end_date=end_date,
        max_cloud_cover=max_cloud_cover,
        limit=limit,
        bbox_override=bbox_override,
    )


@router.post(
    "/scenes/{external_scene_id}/acquire",
    response_model=SceneAcquisitionResponse,
    status_code=status.HTTP_200_OK,
    summary="Acquire and download specified spectral assets for a satellite scene",
)
async def acquire_scene_assets(
    external_scene_id: str = Path(..., description="External scene identifier (e.g. S2A_T45QTB_...)"),
    payload: AcquireAssetsRequest = AcquireAssetsRequest(),
    service: SatelliteService = Depends(get_satellite_service),
) -> SceneAcquisitionResponse:
    return await service.acquire_scene_assets(
        external_scene_id=external_scene_id,
        asset_keys=payload.assets,
    )
