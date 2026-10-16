import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    DateTime,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    water_body_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("water_bodies.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("satellite_scenes.id", ondelete="CASCADE"), nullable=False
    )
    analysis_type: Mapped[str] = mapped_column(String(50), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(50), nullable=False, default="2.0.0")

    # Status: queued, running, completed, failed, cancelled
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    water_body = relationship("WaterBody", back_populates="analysis_runs")
    scene = relationship("SatelliteScene", back_populates="analysis_runs")

    __table_args__ = (
        Index("ix_analysis_runs_water_body_id", "water_body_id"),
        Index("ix_analysis_runs_scene_id", "scene_id"),
        Index("ix_analysis_runs_status", "status"),
        Index("ix_analysis_runs_analysis_type", "analysis_type"),
    )
