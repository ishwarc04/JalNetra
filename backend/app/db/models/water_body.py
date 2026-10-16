import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WaterBody(Base):
    __tablename__ = "water_bodies"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state_province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    water_body_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Geometry stored as GeoJSON text
    geometry_geojson: Mapped[str | None] = mapped_column(Text, nullable=True)
    geometry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Bounding box coordinates
    min_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_lon: Mapped[float | None] = mapped_column(Float, nullable=True)

    centroid_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    centroid_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_sq_km: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationship to future analysis runs
    analysis_runs = relationship(
        "AnalysisRun", back_populates="water_body", cascade="all, delete-orphan"
    )
    # Relationship to water-body-centric satellite observations
    observations = relationship(
        "SatelliteObservation",
        back_populates="water_body",
        cascade="all, delete-orphan",
        order_by="SatelliteObservation.sensing_date",
    )

    __table_args__ = (
        Index("ix_water_bodies_name", "name"),
        Index("ix_water_bodies_normalized_name", "normalized_name"),
        Index("ix_water_bodies_country", "country"),
        Index("ix_water_bodies_source", "source"),
        Index("ix_water_bodies_source_id", "source_id"),
        Index("ix_water_bodies_is_active", "is_active"),
        UniqueConstraint("source", "source_id", name="uq_water_bodies_source_source_id"),
    )
