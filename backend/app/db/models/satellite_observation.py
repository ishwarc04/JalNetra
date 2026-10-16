import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Float,
    Integer,
    DateTime,
    Text,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SatelliteObservation(Base):
    """
    Water-body-centric satellite observation record.
    Represents a targeted visual/analytical observation clipped to a specific water body AOI.
    """
    __tablename__ = "satellite_observations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    water_body_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("water_bodies.id", ondelete="CASCADE"), nullable=False
    )
    satellite: Mapped[str] = mapped_column(String(50), nullable=False, default="Sentinel-2")
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="earth_search")
    collection: Mapped[str] = mapped_column(String(100), nullable=False, default="sentinel-2-c1-l2a")
    external_scene_id: Mapped[str] = mapped_column(String(255), nullable=False)

    sensing_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cloud_cover_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    aoi_bounds: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aoi_geojson: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Local visual JPEG/PNG asset relative to project data/ dir
    local_visual_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Derived water extent (Level 2 analysis)
    derived_water_area_sq_km: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="ready")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationship to parent water body
    water_body = relationship("WaterBody", back_populates="observations")

    __table_args__ = (
        Index("ix_satellite_observations_water_body_id", "water_body_id"),
        Index("ix_satellite_observations_sensing_date", "sensing_date"),
        Index("ix_satellite_observations_external_scene_id", "external_scene_id"),
        Index("ix_satellite_observations_status", "status"),
        UniqueConstraint("water_body_id", "external_scene_id", name="uq_sat_obs_wb_scene"),
    )
