from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.water_body_service import WaterBodyService
from app.schemas.water_body import (
    WaterBodyCreate,
    WaterBodyUpdate,
    WaterBodyRead,
    WaterBodyListResponse,
)
from app.schemas.water_body_summary import WaterBodySummaryResponse

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
    )
