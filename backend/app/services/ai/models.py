from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AIStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    model: str
    provider: str = "openai"


class AIAnalysisRequest(BaseModel):
    water_body_id: Optional[str] = Field(None, description="Water body UUID")
    observation_id: Optional[str] = Field(None, description="Optional observation UUID")
    question: str = Field(..., min_length=2, max_length=1000, description="Question or prompt for AI assistant")


class AIAnalysisResponse(BaseModel):
    answer: str
    water_body_name: Optional[str] = None
    observation_date: Optional[str] = None
    model: str
    disclaimer: str = (
        "JalNetra AI provides observational summaries and remote-sensing proxy interpretations. "
        "These are uncalibrated optical proxies and not certified laboratory or chemical analyses."
    )
