from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class AnalysisRunBase(BaseModel):
    water_body_id: str
    scene_id: str
    analysis_type: str = Field(..., max_length=50)
    pipeline_version: str = Field("2.0.0", max_length=50)
    status: str = Field("queued", max_length=50)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    output_path: Optional[str] = Field(None, max_length=1024)
    metadata_json: Optional[str] = None


class AnalysisRunCreate(AnalysisRunBase):
    pass


class AnalysisRunRead(AnalysisRunBase):
    id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)



class AnalysisRunListResponse(BaseModel):
    items: List[AnalysisRunRead]
    total: int
