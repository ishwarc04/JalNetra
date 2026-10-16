from datetime import datetime
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models.satellite_observation import SatelliteObservation
from app.schemas.satellite_observation import SatelliteObservationCreate


class SatelliteObservationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, observation_id: str) -> Optional[SatelliteObservation]:
        return self.db.execute(
            select(SatelliteObservation).where(SatelliteObservation.id == observation_id)
        ).scalar_one_or_none()

    def get_by_water_body_and_scene(
        self, water_body_id: str, external_scene_id: str
    ) -> Optional[SatelliteObservation]:
        return self.db.execute(
            select(SatelliteObservation).where(
                SatelliteObservation.water_body_id == water_body_id,
                SatelliteObservation.external_scene_id == external_scene_id,
            )
        ).scalar_one_or_none()

    def list_for_water_body(
        self,
        water_body_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[SatelliteObservation]:
        stmt = select(SatelliteObservation).where(
            SatelliteObservation.water_body_id == water_body_id
        )
        if start_date:
            stmt = stmt.where(SatelliteObservation.sensing_date >= start_date)
        if end_date:
            stmt = stmt.where(SatelliteObservation.sensing_date <= end_date)
        stmt = stmt.order_by(SatelliteObservation.sensing_date.asc())
        return list(self.db.execute(stmt).scalars().all())

    def create(self, data: SatelliteObservationCreate) -> SatelliteObservation:
        obs = SatelliteObservation(**data.model_dump())
        self.db.add(obs)
        self.db.commit()
        self.db.refresh(obs)
        return obs

    def update(self, obs: SatelliteObservation) -> SatelliteObservation:
        self.db.add(obs)
        self.db.commit()
        self.db.refresh(obs)
        return obs

    def delete(self, observation_id: str) -> bool:
        obs = self.get_by_id(observation_id)
        if not obs:
            return False
        self.db.delete(obs)
        self.db.commit()
        return True
