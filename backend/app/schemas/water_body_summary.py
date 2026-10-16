from typing import Optional
from pydantic import BaseModel, Field


class WaterBodySummaryResponse(BaseModel):
    """
    Public structured water-body summary schema.
    Excludes internal filesystem paths.
    """
    id: str
    name: str
    location: str
    surface_area_sq_km: Optional[float] = None
    surface_area_text: str
    water_volume: str
    water_volume_is_estimate: bool
    water_volume_note: Optional[str] = None
    latest_observation_id: Optional[str] = None
    latest_observation_date: str
    cloud_cover: str
    apparent_water_extent: str
    observation_count: int
    monitoring_start: Optional[str] = None
    monitoring_end: Optional[str] = None
    observation_frequency: str
    water_quality_label: str
    water_quality_simple_text: str
    quality_is_remote_sensing_proxy: bool
    has_stored_visual_image: bool
    image_url: Optional[str] = None
