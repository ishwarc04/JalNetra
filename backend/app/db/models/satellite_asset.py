import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Integer,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SatelliteAsset(Base):
    __tablename__ = "satellite_assets"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scene_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("satellite_scenes.id", ondelete="CASCADE"), nullable=False
    )
    asset_key: Mapped[str] = mapped_column(String(100), nullable=False)
    asset_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    remote_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="remote")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    scene = relationship("SatelliteScene", back_populates="assets")

    __table_args__ = (
        Index("ix_satellite_assets_scene_id", "scene_id"),
        Index("ix_satellite_assets_asset_key", "asset_key"),
        Index("ix_satellite_assets_status", "status"),
    )
