from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator


class SatelliteObservationBase(BaseModel):
    satellite: str = "Sentinel-2"
    provider: str = "earth_search"
    collection: str = "sentinel-2-c1-l2a"
    external_scene_id: str
    sensing_date: datetime
    cloud_cover_percent: Optional[float] = None
    aoi_bounds: Optional[str] = None
    aoi_geojson: Optional[str] = None
    local_visual_path: str
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    file_size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    derived_water_area_sq_km: Optional[float] = None
    status: str = "ready"
    metadata_json: Optional[str] = None


class SatelliteObservationCreate(SatelliteObservationBase):
    water_body_id: str


class SatelliteObservationRead(SatelliteObservationBase):
    id: str
    water_body_id: str
    created_at: datetime
    updated_at: datetime
    image_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class VisualDataFetchRequest(BaseModel):
    from_date: str = Field(..., description="Start date YYYY-MM-DD")
    to_date: str = Field(..., description="End date YYYY-MM-DD")
    image_count: int = Field(10, ge=1, le=50, description="Target number of observations")

    @field_validator("from_date", "to_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        try:
            datetime.strptime(v.strip(), "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Date '{v}' must be in YYYY-MM-DD format")
        return v.strip()


class VisualDataFetchResponse(BaseModel):
    water_body_id: str
    water_body_name: str
    from_date: str
    to_date: str
    requested_count: int
    available_count: int
    acquired_count: int
    reused_count: int
    failed_count: int
    message: str
    observations: List[SatelliteObservationRead]


class AvailableObservationItem(BaseModel):
    observation_id: str
    scene_id: str
    id: str
    satellite: str = "Sentinel-2"
    platform: str = "Sentinel-2"
    sensing_date: datetime
    sensing_date_str: str
    cloud_cover_percent: float
    quality_label: str = "CLEAR"  # VERY CLEAR, CLEAR, ACCEPTABLE, HIGH CLOUD
    is_high_cloud: bool = False
    already_acquired: bool = False
    is_already_available: bool = False
    existing_observation_id: Optional[str] = None
    existing_image_url: Optional[str] = None
    file_size_bytes: Optional[int] = None


class AvailableObservationsResponse(BaseModel):
    water_body_id: str
    water_body_name: str
    from_date: str
    to_date: str
    max_cloud_cover: float = 40.0
    max_cloud: Optional[float] = None
    include_high_cloud: bool
    total_found: int
    items: List[AvailableObservationItem]


class FetchSelectedVisualDataRequest(BaseModel):
    observation_ids: List[Any] = Field(
        ...,
        description="List of selected Sentinel-2 scene IDs (e.g. S2A_T44QKJ_20240308T052226_L2A) to acquire",
    )

    @field_validator("observation_ids")
    @classmethod
    def validate_observation_ids(cls, v: List[Any]) -> List[str]:
        if not v or len(v) == 0:
            raise ValueError("At least one observation must be selected.")
        clean_ids: List[str] = []
        for idx, item in enumerate(v):
            if item is None or not isinstance(item, str) or not item.strip():
                raise ValueError(f"Observation ID at index {idx} must be a valid non-empty string.")
            clean_ids.append(item.strip())
        if len(clean_ids) > 20:
            raise ValueError("Maximum 20 observations can be fetched at once. Please reduce your selection.")
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for sid in clean_ids:
            if sid not in seen:
                seen.add(sid)
                deduped.append(sid)
        return deduped


class VisualAcquisitionJobResponse(BaseModel):
    job_id: str
    water_body_id: str
    status: str = "queued"  # queued, running, completed, failed
    total: int
    completed: int = 0
    reused: int = 0
    failed: int = 0
    current_index: int = 0
    current_scene_id: Optional[str] = None
    current_stage: str = "QUEUED"  # QUEUED, SEARCHING, READING AOI, COMPOSITING RGB, SAVING, COMPLETED, FAILED
    percent: int = 0
    details: Optional[str] = None
    message: str = ""
    results: List[SatelliteObservationRead] = []
    errors: List[Dict[str, str]] = []
    created_at: datetime
    updated_at: datetime


class ObservationTimelineItem(BaseModel):
    id: str
    water_body_id: str
    external_scene_id: str
    sensing_date: datetime
    sensing_date_str: str
    cloud_cover_percent: Optional[float] = None
    quality_label: str = "CLEAR"  # VERY CLEAR, CLEAR, ACCEPTABLE, HIGH CLOUD
    image_url: str
    file_size_bytes: Optional[int] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    water_extent_sq_km: Optional[float] = None
    is_extent_measured: bool = False
    is_demo_extent: bool = False
    registered_area_sq_km: Optional[float] = None
    change_from_previous_sq_km: Optional[float] = None
    aoi_bounds: Optional[str] = None
    aoi_geojson: Optional[str] = None
    status: str = "ready"


class IndicatorPlaceholder(BaseModel):
    id: str
    label: str
    description: str
    status: str = "coming_soon"
    message: str = "COMING IN ANALYSIS PHASE"
    unit: Optional[str] = None


class TemporalAnalysisResponse(BaseModel):
    water_body_id: str
    water_body_name: str
    country: Optional[str] = None
    area_sq_km: Optional[float] = None
    total_observations: int
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    timeline: List[ObservationTimelineItem]
    indicators: Dict[str, IndicatorPlaceholder]
