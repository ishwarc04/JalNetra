from typing import Optional
from fastapi import APIRouter, Depends, Query, status, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.database import get_db
from app.db.models.satellite_observation import SatelliteObservation
from app.services.water_body_service import WaterBodyService
from app.schemas.water_body import (
    WaterBodyCreate,
    WaterBodyUpdate,
    WaterBodyRead,
    WaterBodyListResponse,
)
from app.schemas.water_body_summary import (
    WaterBodySummaryResponse,
    WaterBodyVisualStatusResponse,
)
from app.services.satellite.image_resolver import ObservationImageResolver

router = APIRouter(prefix="/water-bodies", tags=["Water Bodies"])


def get_water_body_service(db: Session = Depends(get_db)) -> WaterBodyService:
    return WaterBodyService(db)


@router.post(
    "",
    response_model=WaterBodyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new water body",
)
def create_water_body(
    payload: WaterBodyCreate,
    service: WaterBodyService = Depends(get_water_body_service),
) -> WaterBodyRead:
    return service.create_water_body(payload)


@router.get(
    "",
    response_model=WaterBodyListResponse,
    summary="List water bodies with filtering and pagination",
)
def list_water_bodies(
    search: Optional[str] = Query(None, description="Search term for name or description"),
    country: Optional[str] = Query(None, description="Filter by country"),
    source: Optional[str] = Query(None, description="Filter by catalog source"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=200, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    service: WaterBodyService = Depends(get_water_body_service),
) -> WaterBodyListResponse:
    items, total = service.list_water_bodies(
        search=search,
        country=country,
        source=source,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return WaterBodyListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{water_body_id}",
    response_model=WaterBodyRead,
    summary="Get a water body by ID",
)
def get_water_body(
    water_body_id: str,
    service: WaterBodyService = Depends(get_water_body_service),
) -> WaterBodyRead:
    return service.get_water_body(water_body_id)


@router.patch(
    "/{water_body_id}",
    response_model=WaterBodyRead,
    summary="Update a water body",
)
def update_water_body(
    water_body_id: str,
    payload: WaterBodyUpdate,
    service: WaterBodyService = Depends(get_water_body_service),
) -> WaterBodyRead:
    return service.update_water_body(water_body_id, payload)


@router.delete(
    "/{water_body_id}",
    response_model=WaterBodyRead,
    summary="Deactivate a water body (soft deletion)",
)
def deactivate_water_body(
    water_body_id: str,
    service: WaterBodyService = Depends(get_water_body_service),
) -> WaterBodyRead:
    return service.deactivate_water_body(water_body_id)


@router.get(
    "/{water_body_id}/summary",
    response_model=WaterBodySummaryResponse,
    summary="Get consolidated water body telemetry summary",
    description="Returns public telemetry summary including surface area, volume estimates, observation frequency, and water quality proxy without exposing filesystem paths.",
)
def get_water_body_summary(
    water_body_id: str,
    db: Session = Depends(get_db),
) -> WaterBodySummaryResponse:
    from app.services.water_body_summary_service import WaterBodySummaryService
    service = WaterBodySummaryService(db)
    summary = service.get_water_body_summary(water_body_id)
    return WaterBodySummaryResponse(
        id=summary.id,
        name=summary.name,
        location=summary.location,
        surface_area_sq_km=summary.surface_area_sq_km,
        surface_area_text=summary.surface_area_text,
        water_volume=summary.water_volume,
        water_volume_is_estimate=summary.water_volume_is_estimate,
        water_volume_note=summary.water_volume_note,
        latest_observation_id=summary.latest_observation_id,
        latest_observation_date=summary.latest_observation_date,
        cloud_cover=summary.cloud_cover,
        apparent_water_extent=summary.apparent_water_extent,
        observation_count=summary.observation_count,
        monitoring_start=summary.monitoring_start,
        monitoring_end=summary.monitoring_end,
        observation_frequency=summary.observation_frequency,
        water_quality_label=summary.water_quality_label,
        water_quality_simple_text=summary.water_quality_simple_text,
        quality_is_remote_sensing_proxy=summary.quality_is_remote_sensing_proxy,
        has_stored_visual_image=summary.has_stored_visual_image,
        image_url=summary.image_url,
        google_maps_url=summary.google_maps_url,
    )


@router.get(
    "/{water_body_id}/visual-status",
    response_model=WaterBodyVisualStatusResponse,
    summary="Get visual imagery status and diagnostics for a water body",
    description="Returns safe metadata indicating observation counts, image availability, latest dates, and file size without exposing filesystem paths.",
)
def get_water_body_visual_status(
    water_body_id: str,
    db: Session = Depends(get_db),
) -> WaterBodyVisualStatusResponse:
    # Verify water body exists
    service = WaterBodyService(db)
    wb = service.get_water_body(water_body_id)

    stmt = (
        select(SatelliteObservation)
        .where(SatelliteObservation.water_body_id == wb.id)
        .order_by(SatelliteObservation.sensing_date.desc())
    )
    obs_list = db.execute(stmt).scalars().all()
    count = len(obs_list)

    if count == 0:
        return WaterBodyVisualStatusResponse(
            observation_count=0,
            latest_observation_date=None,
            latest_observation_has_image=False,
            latest_valid_image_date=None,
            image_available=False,
            image_size_bytes=None,
        )

    newest_obs = obs_list[0]
    newest_date_str = newest_obs.sensing_date.strftime("%Y-%m-%d")
    newest_has_img = ObservationImageResolver.resolve_visual_image(newest_obs) is not None

    latest_valid = ObservationImageResolver.get_latest_visual_observation(wb.id, db)
    if latest_valid:
        valid_obs, valid_path = latest_valid
        return WaterBodyVisualStatusResponse(
            observation_count=count,
            latest_observation_date=newest_date_str,
            latest_observation_has_image=newest_has_img,
            latest_valid_image_date=valid_obs.sensing_date.strftime("%Y-%m-%d"),
            image_available=True,
            image_size_bytes=valid_path.stat().st_size,
        )
    else:
        return WaterBodyVisualStatusResponse(
            observation_count=count,
            latest_observation_date=newest_date_str,
            latest_observation_has_image=False,
            latest_valid_image_date=None,
            image_available=False,
            image_size_bytes=None,
        )


@router.get(
    "/{water_body_id}/observations/{observation_id}/visual",
    summary="Stream validated local visual satellite image",
    description="Returns verified local visual image asset. Validates water body ownership, guards against path traversal, and returns supported image MIME types.",
)
def get_observation_visual_image(
    water_body_id: str,
    observation_id: str,
    db: Session = Depends(get_db),
):
    stmt = (
        select(SatelliteObservation)
        .where(
            SatelliteObservation.id == observation_id,
            SatelliteObservation.water_body_id == water_body_id,
        )
    )
    obs = db.execute(stmt).scalar_one_or_none()
    if not obs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Observation '{observation_id}' not found for water body '{water_body_id}'.",
        )

    resolved_path = ObservationImageResolver.resolve_visual_image(obs)
    if not resolved_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored visual image file is missing or unreadable.",
        )

    suffix = resolved_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    media_type = media_types.get(suffix, "image/jpeg")

    return FileResponse(
        path=str(resolved_path),
        media_type=media_type,
        filename=f"{water_body_id}_{obs.external_scene_id}_visual{suffix}",
    )
