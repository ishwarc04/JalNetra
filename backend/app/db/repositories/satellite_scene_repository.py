from typing import List, Optional, Tuple
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db.models.satellite_scene import SatelliteScene
from app.schemas.satellite_scene import SatelliteSceneCreate


class SatelliteSceneRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, scene_id: str) -> Optional[SatelliteScene]:
        return self.db.execute(
            select(SatelliteScene).where(SatelliteScene.id == scene_id)
        ).scalar_one_or_none()

    def get_by_external_id(self, external_scene_id: str) -> Optional[SatelliteScene]:
        return self.db.execute(
            select(SatelliteScene).where(
                SatelliteScene.external_scene_id == external_scene_id
            )
        ).scalar_one_or_none()

    def list_scenes(
        self,
        provider: Optional[str] = None,
        collection: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[SatelliteScene], int]:
        stmt = select(SatelliteScene)
        if provider:
            stmt = stmt.where(SatelliteScene.provider == provider)
        if collection:
            stmt = stmt.where(SatelliteScene.collection == collection)
        if status:
            stmt = stmt.where(SatelliteScene.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.db.execute(count_stmt).scalar() or 0

        stmt = stmt.order_by(SatelliteScene.sensing_start.desc()).limit(limit).offset(offset)
        items = list(self.db.execute(stmt).scalars().all())
        return items, total

    def create(self, data: SatelliteSceneCreate) -> SatelliteScene:
        scene = SatelliteScene(**data.model_dump())
        self.db.add(scene)
        self.db.commit()
        self.db.refresh(scene)
        return scene
