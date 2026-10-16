from typing import List, Optional, Tuple
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from app.db.models.water_body import WaterBody
from app.schemas.water_body import WaterBodyCreate, WaterBodyUpdate, compute_geometry_hash


class WaterBodyRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, water_body_id: str) -> Optional[WaterBody]:
        return self.db.execute(
            select(WaterBody).where(WaterBody.id == water_body_id)
        ).scalar_one_or_none()

    def get_by_source_and_source_id(
        self, source: str, source_id: str
    ) -> Optional[WaterBody]:
        return self.db.execute(
            select(WaterBody).where(
                WaterBody.source == source, WaterBody.source_id == source_id
            )
        ).scalar_one_or_none()

    def list_water_bodies(
        self,
        search: Optional[str] = None,
        country: Optional[str] = None,
        source: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[WaterBody], int]:
        stmt = select(WaterBody)

        if search:
            search_pattern = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(WaterBody.name).like(search_pattern),
                    func.lower(WaterBody.normalized_name).like(search_pattern),
                    func.lower(WaterBody.description).like(search_pattern),
                )
            )

        if country:
            stmt = stmt.where(func.lower(WaterBody.country) == country.strip().lower())

        if source:
            stmt = stmt.where(WaterBody.source == source.strip())

        if is_active is not None:
            stmt = stmt.where(WaterBody.is_active == is_active)

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.db.execute(count_stmt).scalar() or 0

        # Order and paginate
        stmt = stmt.order_by(WaterBody.created_at.desc()).limit(limit).offset(offset)
        items = list(self.db.execute(stmt).scalars().all())

        return items, total

    def create(self, data: WaterBodyCreate) -> WaterBody:
        normalized_name = data.name.strip().lower()
        geo_hash = compute_geometry_hash(data.geometry_geojson)

        water_body = WaterBody(
            name=data.name,
            normalized_name=normalized_name,
            country=data.country,
            state_province=data.state_province,
            district=data.district,
            city=data.city,
            source=data.source,
            source_id=data.source_id,
            water_body_type=data.water_body_type,
            description=data.description,
            geometry_geojson=data.geometry_geojson,
            geometry_hash=geo_hash,
            min_lat=data.min_lat,
            min_lon=data.min_lon,
            max_lat=data.max_lat,
            max_lon=data.max_lon,
            centroid_lat=data.centroid_lat,
            centroid_lon=data.centroid_lon,
            area_sq_km=data.area_sq_km,
            is_active=data.is_active,
        )
        self.db.add(water_body)
        self.db.commit()
        self.db.refresh(water_body)
        return water_body

    def update(self, water_body: WaterBody, data: WaterBodyUpdate) -> WaterBody:
        update_dict = data.model_dump(exclude_unset=True)

        if "name" in update_dict and update_dict["name"]:
            water_body.name = update_dict["name"]
            water_body.normalized_name = update_dict["name"].strip().lower()

        if "geometry_geojson" in update_dict:
            water_body.geometry_geojson = update_dict["geometry_geojson"]
            water_body.geometry_hash = compute_geometry_hash(update_dict["geometry_geojson"])

        for field in [
            "country",
            "state_province",
            "district",
            "city",
            "source",
            "source_id",
            "water_body_type",
            "description",
            "min_lat",
            "min_lon",
            "max_lat",
            "max_lon",
            "centroid_lat",
            "centroid_lon",
            "area_sq_km",
            "is_active",
        ]:
            if field in update_dict:
                setattr(water_body, field, update_dict[field])

        self.db.commit()
        self.db.refresh(water_body)
        return water_body

    def deactivate(self, water_body: WaterBody) -> WaterBody:
        water_body.is_active = False
        self.db.commit()
        self.db.refresh(water_body)
        return water_body
