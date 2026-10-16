import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.spectral import (
    SpectralAnalysisService,
    SpectralServiceError,
    SpectralAnalysisResult,
    BandAvailabilityInfo,
    AnalyzeIndicatorRequest,
    TimeSeriesSpectralRequest,
    TimeSeriesSpectralResponse,
    MultiIndicatorSummary,
)

logger = logging.getLogger("jalnetra.api.spectral")
router = APIRouter(prefix="/water-bodies", tags=["Spectral Analysis"])


def get_spectral_service(db: Session = Depends(get_db)) -> SpectralAnalysisService:
    return SpectralAnalysisService(db)


@router.get(
    "/{water_body_id}/spectral/available",
    response_model=BandAvailabilityInfo,
    summary="Check spectral band availability for an observation and indicator",
)
@router.get(
    "/{water_body_id}/spectral/bands",
    response_model=BandAvailabilityInfo,
    include_in_schema=False,
)
def check_band_availability(
    water_body_id: str,
    observation_id: str = Query(..., description="ID of the satellite observation"),
    indicator: str = Query(..., description="Indicator ID: ndti, ndci, fai, anomaly"),
    service: SpectralAnalysisService = Depends(get_spectral_service),
) -> BandAvailabilityInfo:
    try:
        return service.check_band_availability(
            water_body_id=water_body_id,
            observation_id=observation_id,
            indicator=indicator,
        )
    except SpectralServiceError as exc:
        status_code = status.HTTP_404_NOT_FOUND if "NOT_FOUND" in exc.code else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})


@router.post(
    "/{water_body_id}/spectral/analyze",
    response_model=SpectralAnalysisResult,
    summary="Perform on-demand lazy spectral calculation for an indicator",
)
async def analyze_spectral_indicator(
    water_body_id: str,
    payload: AnalyzeIndicatorRequest,
    service: SpectralAnalysisService = Depends(get_spectral_service),
) -> SpectralAnalysisResult:
    try:
        return await service.analyze_indicator(
            water_body_id=water_body_id,
            observation_id=payload.observation_id,
            indicator=payload.indicator,
            force_recompute=payload.force_recompute,
        )
    except SpectralServiceError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "NOT_FOUND" in exc.code
            else status.HTTP_422_UNPROCESSABLE_ENTITY
            if exc.code == "MISSING_SPECTRAL_BANDS"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message, "details": exc.details},
        )
    except Exception as exc:
        logger.error("Spectral analysis unexpected failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "INTERNAL_ERROR", "message": str(exc)},
        )


@router.get(
    "/{water_body_id}/spectral/results/{result_id}/image",
    summary="Serve the compact colormapped preview image for a spectral result",
)
def get_spectral_preview_image(
    water_body_id: str,
    result_id: str,
    service: SpectralAnalysisService = Depends(get_spectral_service),
):
    try:
        file_path = service.get_preview_image_path(water_body_id=water_body_id, result_id=result_id)
        return FileResponse(
            path=str(file_path),
            media_type="image/png",
            filename=f"{result_id}_preview.png",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except SpectralServiceError as exc:
        status_code = status.HTTP_404_NOT_FOUND if "NOT_FOUND" in exc.code else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})


@router.post(
    "/{water_body_id}/spectral/time-series",
    response_model=TimeSeriesSpectralResponse,
    summary="Compute indicator time series across multiple selected observations",
)
async def run_time_series_spectral(
    water_body_id: str,
    payload: TimeSeriesSpectralRequest,
    service: SpectralAnalysisService = Depends(get_spectral_service),
) -> TimeSeriesSpectralResponse:
    try:
        return await service.run_time_series_analysis(
            water_body_id=water_body_id,
            observation_ids=payload.observation_ids,
            indicator=payload.indicator,
            force_recompute=payload.force_recompute,
        )
    except SpectralServiceError as exc:
        status_code = status.HTTP_404_NOT_FOUND if "NOT_FOUND" in exc.code else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})


@router.get(
    "/{water_body_id}/spectral/summary",
    response_model=MultiIndicatorSummary,
    summary="Get multi-indicator comparison summary for an observation",
)
def get_multi_indicator_summary(
    water_body_id: str,
    observation_id: str = Query(..., description="ID of the satellite observation"),
    service: SpectralAnalysisService = Depends(get_spectral_service),
) -> MultiIndicatorSummary:
    try:
        return service.get_multi_indicator_summary(
            water_body_id=water_body_id,
            observation_id=observation_id,
        )
    except SpectralServiceError as exc:
        status_code = status.HTTP_404_NOT_FOUND if "NOT_FOUND" in exc.code else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})
