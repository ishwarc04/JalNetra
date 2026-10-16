import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Float,
    DateTime,
    Text,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SatelliteScene(Base):
    __tablename__ = "satellite_scenes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    collection: Mapped[str] = mapped_column(String(100), nullable=False)
    external_scene_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    product_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    sensing_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sensing_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cloud_cover_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    processing_level: Mapped[str | None] = mapped_column(String(50), nullable=True)

    bbox_min_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_min_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_max_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_max_lon: Mapped[float | None] = mapped_column(Float, nullable=True)

    footprint_geojson: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status: discovered, queued, downloading, downloaded, processing, processed, failed
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="discovered")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    assets = relationship(
        "SatelliteAsset", back_populates="scene", cascade="all, delete-orphan"
    )
    analysis_runs = relationship(
        "AnalysisRun", back_populates="scene", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_satellite_scenes_provider", "provider"),
        Index("ix_satellite_scenes_collection", "collection"),
        Index("ix_satellite_scenes_external_scene_id", "external_scene_id"),
        Index("ix_satellite_scenes_sensing_start", "sensing_start"),
        Index("ix_satellite_scenes_status", "status"),
    )
