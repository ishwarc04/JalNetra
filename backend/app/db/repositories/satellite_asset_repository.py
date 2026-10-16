from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models.satellite_asset import SatelliteAsset
from app.schemas.satellite_asset import SatelliteAssetCreate


class SatelliteAssetRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, asset_id: str) -> Optional[SatelliteAsset]:
        return self.db.execute(
            select(SatelliteAsset).where(SatelliteAsset.id == asset_id)
        ).scalar_one_or_none()

    def list_by_scene_id(self, scene_id: str) -> List[SatelliteAsset]:
        return list(
            self.db.execute(
                select(SatelliteAsset).where(SatelliteAsset.scene_id == scene_id)
            ).scalars().all()
        )

    def create(self, data: SatelliteAssetCreate) -> SatelliteAsset:
        asset = SatelliteAsset(**data.model_dump())
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset
