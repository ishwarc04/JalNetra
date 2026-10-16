from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models.analysis_run import AnalysisRun
from app.schemas.analysis_run import AnalysisRunCreate


class AnalysisRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, run_id: str) -> Optional[AnalysisRun]:
        return self.db.execute(
            select(AnalysisRun).where(AnalysisRun.id == run_id)
        ).scalar_one_or_none()

    def list_by_water_body_id(self, water_body_id: str) -> List[AnalysisRun]:
        return list(
            self.db.execute(
                select(AnalysisRun).where(AnalysisRun.water_body_id == water_body_id)
            ).scalars().all()
        )

    def list_by_scene_id(self, scene_id: str) -> List[AnalysisRun]:
        return list(
            self.db.execute(
                select(AnalysisRun).where(AnalysisRun.scene_id == scene_id)
            ).scalars().all()
        )

    def create(self, data: AnalysisRunCreate) -> AnalysisRun:
        run = AnalysisRun(**data.model_dump())
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run
