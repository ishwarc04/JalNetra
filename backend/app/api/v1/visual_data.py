import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import get_db, SessionLocal
from app.schemas.satellite_observation import (
    VisualDataFetchRequest,
    VisualDataFetchResponse,
    AvailableObservationsResponse,
    FetchSelectedVisualDataRequest,
    VisualAcquisitionJobResponse,
    SatelliteObservationRead,
)
from app.services.satellite.observation_service import (
    SatelliteObservationService,
    ObservationServiceError,
)
from app.services.satellite.job_manager import job_manager

logger = logging.getLogger("jalnetra.api.visual_data")
router = APIRouter(prefix="/water-bodies", tags=["Visual Data"])


def get_observation_service(db: Session = Depends(get_db)) -> SatelliteObservationService:
    return SatelliteObservationService(db)


async def _run_acquisition_job(water_body_id: str, observation_ids: List[str], job_id: str, bind=None):
    """Background runner for visual data acquisition job with isolated DB session."""
    if bind is not None:
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=bind)
        db = session_factory()
    else:
        db = SessionLocal()
    try:
        service = SatelliteObservationService(db)
        await service.fetch_selected_observations(
            water_body_id=water_body_id,
            observation_ids=observation_ids,
            job_id=job_id,
        )
    except Exception as exc:
        logger.error("Background acquisition job %s failed: %s", job_id, exc)
        await job_manager.update_job(
            job_id,
            status="failed",
            current_stage="FAILED",
            message=f"Job failed: {str(exc)}",
        )
    finally:
        db.close()


@router.get(
    "/{water_body_id}/visual-data/available",
    response_model=AvailableObservationsResponse,
    summary="Search available visual satellite observations metadata for a water body",
    description="Queries STAC metadata only. Does NOT download any raster data or imagery.",
)
async def get_available_visual_data(
    water_body_id: str,
    from_date: str = Query(..., description="Start date YYYY-MM-DD"),
    to_date: str = Query(..., description="End date YYYY-MM-DD"),
    max_cloud: float = Query(40.0, ge=0.0, le=100.0, description="Maximum cloud cover percentage (default 40.0)"),
    include_high_cloud: bool = Query(False, description="Whether to include observations above max_cloud"),
    sort: str = Query("newest", description="Sort order: newest, oldest, lowest_cloud"),
    service: SatelliteObservationService = Depends(get_observation_service),
) -> AvailableObservationsResponse:
    try:
        return await service.get_available_observations(
            water_body_id=water_body_id,
            from_date=from_date,
            to_date=to_date,
            max_cloud=max_cloud,
            include_high_cloud=include_high_cloud,
            sort=sort,
        )
    except ObservationServiceError as exc:
        status_code = status.HTTP_404_NOT_FOUND if exc.code == "WATER_BODY_NOT_FOUND" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "INTERNAL_ERROR", "message": str(exc)},
        )


@router.post(
    "/{water_body_id}/visual-data/fetch-selected",
    response_model=VisualAcquisitionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger visual data acquisition for explicitly selected observations",
    description="Dispatches a background visual acquisition job for selected observation IDs (max 20).",
)
async def fetch_selected_visual_data(
    water_body_id: str,
    payload: FetchSelectedVisualDataRequest,
    background_tasks: BackgroundTasks,
    service: SatelliteObservationService = Depends(get_observation_service),
    db: Session = Depends(get_db),
) -> VisualAcquisitionJobResponse:
    try:
        service._get_water_body_or_404(water_body_id)
        job = await job_manager.create_job(
            water_body_id=water_body_id,
            total=len(payload.observation_ids),
            initial_message=f"Acquisition queued for {len(payload.observation_ids)} observations",
        )
        bind = db.get_bind()
        background_tasks.add_task(
            _run_acquisition_job,
            water_body_id=water_body_id,
            observation_ids=payload.observation_ids,
            job_id=job.job_id,
            bind=bind,
        )
        return job
    except ObservationServiceError as exc:
        status_code = status.HTTP_404_NOT_FOUND if exc.code == "WATER_BODY_NOT_FOUND" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "INTERNAL_ERROR", "message": str(exc)},
        )


@router.get(
    "/{water_body_id}/visual-data/jobs/{job_id}",
    response_model=VisualAcquisitionJobResponse,
    summary="Check status and real-time progress of a visual acquisition job",
)
async def get_visual_acquisition_job_status(
    water_body_id: str,
    job_id: str,
    service: SatelliteObservationService = Depends(get_observation_service),
) -> VisualAcquisitionJobResponse:
    try:
        service._get_water_body_or_404(water_body_id)
        job = await job_manager.get_job(job_id)
        if not job or job.water_body_id != water_body_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "JOB_NOT_FOUND", "message": f"Acquisition job '{job_id}' not found."},
            )
        return job
    except ObservationServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": exc.code, "message": exc.message})


@router.post(
    "/{water_body_id}/visual-data/fetch",
    response_model=VisualDataFetchResponse,
    status_code=status.HTTP_200_OK,
    summary="Fetch targeted visual satellite observations across date range (legacy)",
)
async def fetch_visual_data(
    water_body_id: str,
    payload: VisualDataFetchRequest,
    service: SatelliteObservationService = Depends(get_observation_service),
) -> VisualDataFetchResponse:
    try:
        return await service.fetch_visual_data(water_body_id=water_body_id, request=payload)
    except ObservationServiceError as exc:
        status_code = status.HTTP_400_BAD_REQUEST
        if exc.code == "WATER_BODY_NOT_FOUND":
            status_code = status.HTTP_404_NOT_FOUND
        elif exc.code == "SECURITY_VIOLATION":
            status_code = status.HTTP_403_FORBIDDEN
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "INTERNAL_ERROR", "message": str(exc)},
        )


@router.get(
    "/{water_body_id}/observations",
    response_model=List[SatelliteObservationRead],
    summary="List all acquired satellite observations for a water body",
)
def list_observations(
    water_body_id: str,
    from_date: Optional[str] = Query(None, description="Filter start date YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="Filter end date YYYY-MM-DD"),
    service: SatelliteObservationService = Depends(get_observation_service),
) -> List[SatelliteObservationRead]:
    try:
        return service.list_observations_for_water_body(
            water_body_id=water_body_id, from_date=from_date, to_date=to_date
        )
    except ObservationServiceError as exc:
        status_code = status.HTTP_404_NOT_FOUND if exc.code == "WATER_BODY_NOT_FOUND" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
        )


@router.get(
    "/{water_body_id}/observations/{observation_id}/image",
    summary="Serve the visual RGB JPEG or filtered image of an observation",
)
def get_observation_image(
    water_body_id: str,
    observation_id: str,
    filter: str = Query("natural", description="Visual filter: natural, water_emphasis, contrast, false_color, nir, swir"),
    service: SatelliteObservationService = Depends(get_observation_service),
):
    try:
        file_path, media_type, raw_bytes = service.get_filtered_observation_image(
            water_body_id=water_body_id, observation_id=observation_id, filter_type=filter
        )
        if raw_bytes is not None:
            return Response(
                content=raw_bytes,
                media_type=media_type,
                headers={"Cache-Control": "public, max-age=86400"},
            )
        return FileResponse(
            path=str(file_path),
            media_type=media_type,
            filename=f"{observation_id}_{filter}.jpg",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except ObservationServiceError as exc:
        status_code = status.HTTP_404_NOT_FOUND
        if exc.code == "SECURITY_VIOLATION":
            status_code = status.HTTP_403_FORBIDDEN
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
        )
