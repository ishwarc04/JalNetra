import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.ai import (
    AIService,
    AIServiceError,
    AIStatusResponse,
    AIAnalysisRequest,
    AIAnalysisResponse,
)

logger = logging.getLogger("jalnetra.api.ai")
router = APIRouter(prefix="/ai", tags=["AI Assistant"])


def get_ai_service(db: Session = Depends(get_db)) -> AIService:
    return AIService(db=db)


@router.get(
    "/status",
    response_model=AIStatusResponse,
    summary="Get JalNetra AI assistant status and configuration",
    description="Returns whether AI assistance is enabled and configured. Never exposes API keys.",
)
def get_ai_status(service: AIService = Depends(get_ai_service)) -> AIStatusResponse:
    return service.get_status()


@router.post(
    "/analyze",
    response_model=AIAnalysisResponse,
    summary="Ask JalNetra AI assistant an analysis or observation question",
    description="Retrieves official water body context and answers questions in scientifically cautious language.",
)
def ask_ai_analysis(
    payload: AIAnalysisRequest,
    service: AIService = Depends(get_ai_service),
) -> AIAnalysisResponse:
    try:
        return service.generate_analysis_response(
            water_body_id=payload.water_body_id,
            observation_id=payload.observation_id,
            question=payload.question,
        )
    except AIServiceError as exc:
        logger.warning("AI Service error [%s]: %s", exc.code, exc.message)
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        )
