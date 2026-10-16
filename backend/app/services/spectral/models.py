from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class IndicatorType(str, Enum):
    NDTI = "ndti"
    NDCI = "ndci"
    FAI = "fai"
    ANOMALY = "anomaly"


class QualityLevel(str, Enum):
    GOOD = "GOOD"
    LIMITED = "LIMITED"
    INSUFFICIENT = "INSUFFICIENT"


class BandAvailabilityInfo(BaseModel):
    observation_id: str
    external_scene_id: str
    indicator: str
    required_bands: List[str]
    available_bands: List[str]
    missing_bands: List[str]
    is_ready: bool
    message: str


class SpectralAnalysisResult(BaseModel):
    id: str
    water_body_id: str
    water_body_name: str
    observation_id: str
    external_scene_id: str
    sensing_date: datetime
    sensing_date_str: str
    indicator: str
    indicator_label: str
    index_name: str
    value: Optional[float] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    std: Optional[float] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    valid_pixel_count: int = 0
    total_water_pixels: int = 0
    valid_pixel_percent: float = 0.0
    cloud_pixel_percent: float = 0.0
    quality: str = QualityLevel.GOOD.value
    quality_reason: Optional[str] = None
    classification: str = "UNKNOWN"
    classification_desc: str = ""
    baseline_mean: Optional[float] = None
    baseline_std: Optional[float] = None
    anomaly_score: Optional[float] = None
    preview_url: Optional[str] = None
    formula: str = ""
    disclaimer: str = ""
    required_bands: List[str] = []
    available_bands: List[str] = []
    missing_bands: List[str] = []
    formula_version: str = "2.0.0"
    processing_version: str = "2.0.0"
    is_cached: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AnalyzeIndicatorRequest(BaseModel):
    observation_id: str
    indicator: str  # "ndti", "ndci", "fai", "anomaly"
    force_recompute: bool = False


class TimeSeriesSpectralRequest(BaseModel):
    observation_ids: List[str]
    indicator: str  # "ndti", "ndci", "fai", "anomaly"
    force_recompute: bool = False


class TimeSeriesSpectralResponse(BaseModel):
    water_body_id: str
    water_body_name: str
    indicator: str
    total_requested: int
    total_analyzed: int
    results: List[SpectralAnalysisResult]


class MultiIndicatorSummary(BaseModel):
    water_body_id: str
    observation_id: str
    sensing_date_str: str
    indicators: Dict[str, Optional[SpectralAnalysisResult]]
