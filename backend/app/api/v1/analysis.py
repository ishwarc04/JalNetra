from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.satellite_observation import TemporalAnalysisResponse
from app.services.satellite.observation_service import (
    SatelliteObservationService,
    ObservationServiceError,
)

router = APIRouter(prefix="/analysis", tags=["Analysis"])


def get_observation_service(db: Session = Depends(get_db)) -> SatelliteObservationService:
    return SatelliteObservationService(db)


@router.get(
    "/water-bodies/{water_body_id}",
    response_model=TemporalAnalysisResponse,
    summary="Get temporal water monitoring analysis data for a water body",
    description=(
        "Returns chronological visual observation history, apparent water extent changes, "
        "and extensible indicator placeholders (turbidity, chlorophyll, algae, anomaly) "
        "without generating uncalibrated or fake values."
    ),
)
def get_water_body_temporal_analysis(
    water_body_id: str,
    from_date: Optional[str] = Query(None, description="Optional filter start date YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="Optional filter end date YYYY-MM-DD"),
    service: SatelliteObservationService = Depends(get_observation_service),
) -> TemporalAnalysisResponse:
    try:
        return service.get_temporal_analysis(
            water_body_id=water_body_id, from_date=from_date, to_date=to_date
        )
    except ObservationServiceError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code == "WATER_BODY_NOT_FOUND"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
        )
