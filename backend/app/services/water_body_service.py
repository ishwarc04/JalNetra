from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from app.db.models.water_body import WaterBody
from app.db.repositories.water_body_repository import WaterBodyRepository
from app.schemas.water_body import WaterBodyCreate, WaterBodyUpdate


class WaterBodyConflictError(Exception):
    """Raised when a unique constraint or conflicting record is found."""
    pass


class WaterBodyNotFoundError(Exception):
    """Raised when a water body cannot be found."""
    pass


class WaterBodyService:
    def __init__(self, db: Session):
        self.repo = WaterBodyRepository(db)

    def create_water_body(self, data: WaterBodyCreate) -> WaterBody:
        # Check source & source_id uniqueness if source_id is provided
        if data.source_id:
            existing = self.repo.get_by_source_and_source_id(data.source, data.source_id)
            if existing:
                raise WaterBodyConflictError(
                    f"A water body with source '{data.source}' and source_id '{data.source_id}' already exists."
                )
        return self.repo.create(data)

    def get_water_body(self, water_body_id: str) -> WaterBody:
        water_body = self.repo.get_by_id(water_body_id)
        if not water_body:
            raise WaterBodyNotFoundError(f"Water body with ID '{water_body_id}' not found.")
        return water_body

    def list_water_bodies(
        self,
        search: Optional[str] = None,
        country: Optional[str] = None,
        source: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[WaterBody], int]:
        return self.repo.list_water_bodies(
            search=search,
            country=country,
            source=source,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

    def update_water_body(
        self, water_body_id: str, data: WaterBodyUpdate
    ) -> WaterBody:
        water_body = self.get_water_body(water_body_id)

        # Check source/source_id uniqueness conflict if updating those fields
        target_source = data.source if data.source is not None else water_body.source
        target_source_id = data.source_id if data.source_id is not None else water_body.source_id

        if target_source_id:
            existing = self.repo.get_by_source_and_source_id(target_source, target_source_id)
            if existing and existing.id != water_body_id:
                raise WaterBodyConflictError(
                    f"A water body with source '{target_source}' and source_id '{target_source_id}' already exists."
                )

        return self.repo.update(water_body, data)

    def deactivate_water_body(self, water_body_id: str) -> WaterBody:
        water_body = self.get_water_body(water_body_id)
        return self.repo.deactivate(water_body)
