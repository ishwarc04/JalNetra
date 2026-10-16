import hashlib
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import settings
from app.db.models.satellite_scene import SatelliteScene
from app.db.models.satellite_asset import SatelliteAsset
from app.db.repositories.satellite_scene_repository import SatelliteSceneRepository
from app.db.repositories.satellite_asset_repository import SatelliteAssetRepository
from app.db.repositories.water_body_repository import WaterBodyRepository
from app.schemas.satellite_scene import SatelliteSceneCreate
from app.schemas.satellite_asset import SatelliteAssetCreate
from app.services.storage_service import LocalStorageService, storage_service
from app.services.satellite.base import SatelliteProvider
from app.services.satellite.cache import SatelliteCacheService
from app.services.satellite.models import (
    NormalizedScene,
    NormalizedAsset,
    SceneSearchResponse,
    SceneAcquisitionResponse,
    AssetAcquisitionStatus,
)
from app.services.satellite.providers.stac import EarthSearchSTACProvider
from app.services.satellite.ranking import rank_and_score_scenes

logger = logging.getLogger("jalnetra.satellite.service")


class SatelliteServiceError(Exception):
    def __init__(self, message: str, code: str = "SATELLITE_SERVICE_ERROR"):
        super().__init__(message)
        self.code = code
        self.message = message


class SatelliteService:
    """
    Coordinates Sentinel-2 satellite scene search, ranking, and local asset acquisition.
    """

    def __init__(
        self,
        db: Session,
        provider: Optional[SatelliteProvider] = None,
        storage: Optional[LocalStorageService] = None,
    ):
        self.db = db
        self.provider = provider or EarthSearchSTACProvider()
        self.storage = storage or storage_service
        self.scene_repo = SatelliteSceneRepository(db)
        self.asset_repo = SatelliteAssetRepository(db)
        self.wb_repo = WaterBodyRepository(db)
        self.cache = SatelliteCacheService(db, storage=self.storage)

    async def search_scenes_for_water_body(
        self,
        water_body_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        max_cloud_cover: float = 30.0,
        limit: int = 10,
        bbox_override: Optional[List[float]] = None,
    ) -> SceneSearchResponse:
        wb = self.wb_repo.get_by_id(water_body_id) if water_body_id else None
        if not wb and not bbox_override:
            raise SatelliteServiceError(
                f"Water body with ID '{water_body_id}' not found.",
                code="WATER_BODY_NOT_FOUND",
            )

        # Parse geometry or fallback to bounding box [min_lon, min_lat, max_lon, max_lat]
        geometry_dict = None
        bbox = None

        if bbox_override:
            bbox = bbox_override
        elif wb:
            if wb.geometry_geojson:
                try:
                    parsed = json.loads(wb.geometry_geojson)
                    if parsed.get("type") in ("Polygon", "MultiPolygon", "Point"):
                        geometry_dict = parsed
                except Exception:
                    pass

            if wb.min_lon is not None and wb.min_lat is not None and wb.max_lon is not None and wb.max_lat is not None:
                bbox = [wb.min_lon, wb.min_lat, wb.max_lon, wb.max_lat]
            elif wb.centroid_lon is not None and wb.centroid_lat is not None:
                # Point expansion into minimal 0.02 deg box (~2 km)
                bbox = [
                    wb.centroid_lon - 0.01,
                    wb.centroid_lat - 0.01,
                    wb.centroid_lon + 0.01,
                    wb.centroid_lat + 0.01,
                ]

        if not geometry_dict and not bbox:
            wb_name = wb.name if wb else "AOI"
            raise SatelliteServiceError(
                f"Water body '{wb_name}' does not have geographic coordinates or bounding box.",
                code="MISSING_GEOMETRY",
            )

        # Check Cache
        s_str = start_date.isoformat() if start_date else None
        e_str = end_date.isoformat() if end_date else None
        cache_key = self.cache.build_cache_key(
            self.provider.name,
            self.provider.collection,
            water_body_id,
            s_str,
            e_str,
            max_cloud_cover,
            limit,
        )

        cached_raw = self.cache.get(cache_key)
        if cached_raw is not None:
            logger.info("Satellite STAC cache hit for '%s'", cache_key)
            cached_scenes = [NormalizedScene.model_validate(item) for item in cached_raw]
            return SceneSearchResponse(
                water_body_id=water_body_id,
                provider=self.provider.name,
                collection=self.provider.collection,
                results=cached_scenes,
            )

        # Call Provider
        logger.info("Executing STAC search on '%s' for water body '%s'", self.provider.name, wb.name)
        try:
            raw_scenes = await self.provider.search_scenes(
                geometry=geometry_dict,
                bbox=bbox,
                start_date=start_date,
                end_date=end_date,
                max_cloud_cover=max_cloud_cover,
                limit=limit,
            )
        except Exception as exc:
            logger.error("STAC search failed on provider '%s': %s", self.provider.name, exc)
            raise SatelliteServiceError(
                f"Satellite STAC provider error: {str(exc)}",
                code="STAC_SEARCH_FAILED",
            )

        # Deterministic Ranking
        ranked_scenes = rank_and_score_scenes(raw_scenes, target_bbox=bbox)

        # Cache valid response
        scenes_dump = [s.model_dump(mode="json") for s in ranked_scenes]
        self.cache.set(cache_key, self.provider.name, water_body_id, scenes_dump)

        return SceneSearchResponse(
            water_body_id=water_body_id,
            provider=self.provider.name,
            collection=self.provider.collection,
            results=ranked_scenes,
        )

    def get_or_create_scene_record(self, scene: NormalizedScene) -> SatelliteScene:
        """
        Retrieves or creates a persistent SatelliteScene record idempotently.
        """
        existing = self.scene_repo.get_by_external_id(scene.external_scene_id)
        if existing:
            return existing

        # Extract bbox lat/lon
        min_lat, min_lon, max_lat, max_lon = None, None, None, None
        if scene.bbox and len(scene.bbox) >= 4:
            min_lon, min_lat, max_lon, max_lat = scene.bbox[:4]

        footprint_str = json.dumps(scene.footprint_geojson) if scene.footprint_geojson else None

        dto = SatelliteSceneCreate(
            provider=scene.provider,
            collection=scene.collection,
            external_scene_id=scene.external_scene_id,
            product_id=scene.product_id,
            sensing_start=scene.sensing_start,
            sensing_end=scene.sensing_end,
            cloud_cover_percent=scene.cloud_cover_percent,
            processing_level=scene.processing_level or "L2A",
            bbox_min_lat=min_lat,
            bbox_min_lon=min_lon,
            bbox_max_lat=max_lat,
            bbox_max_lon=max_lon,
            footprint_geojson=footprint_str,
            metadata_json=scene.metadata_json,
            status="discovered",
        )
        return self.scene_repo.create(dto)

    async def acquire_scene_assets(
        self,
        external_scene_id: str,
        asset_keys: List[str],
    ) -> SceneAcquisitionResponse:
        """
        Downloads requested spectral assets for a scene with streaming atomic writes,
        SHA256 calculation, and database registration.
        """
        # 1. Fetch Scene from STAC provider or DB
        scene = await self.provider.get_scene(external_scene_id)
        if not scene:
            # Fallback check if existing in database
            db_scene = self.scene_repo.get_by_external_id(external_scene_id)
            if not db_scene:
                raise SatelliteServiceError(
                    f"Scene '{external_scene_id}' not found on provider or database.",
                    code="SCENE_NOT_FOUND",
                )
            # Reconstruct scene from DB
            scene = NormalizedScene(
                provider=db_scene.provider,
                collection=db_scene.collection,
                external_scene_id=db_scene.external_scene_id,
                product_id=db_scene.product_id,
                sensing_start=db_scene.sensing_start,
                sensing_end=db_scene.sensing_end,
                cloud_cover_percent=db_scene.cloud_cover_percent,
                processing_level=db_scene.processing_level,
                metadata_json=db_scene.metadata_json,
            )

        db_scene = self.get_or_create_scene_record(scene)
        db_scene_id = db_scene.id

        # Target scene directory: data/scenes/{scene_id}/
        scene_dir = self.storage.get_scene_dir(db_scene_id)
        assets_dir = scene_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        # Save metadata.json in scene dir
        meta_file = scene_dir / "metadata.json"
        if not meta_file.exists():
            meta_content = {
                "scene_id": db_scene_id,
                "external_scene_id": scene.external_scene_id,
                "provider": scene.provider,
                "collection": scene.collection,
                "sensing_start": scene.sensing_start.isoformat(),
                "cloud_cover_percent": scene.cloud_cover_percent,
            }
            self.storage.save_bytes(
                f"scenes/{db_scene_id}/metadata.json",
                json.dumps(meta_content, indent=2).encode("utf-8"),
            )

        statuses: List[AssetAcquisitionStatus] = []
        downloaded_count = 0
        failed_count = 0
        already_present_count = 0

        # Existing assets in DB for this scene
        existing_assets = {a.asset_key: a for a in self.asset_repo.list_by_scene_id(db_scene_id)}

        for key in asset_keys:
            norm_key = key.upper() if key.lower() not in ("thumbnail", "preview", "visual") else key.lower()
            if norm_key not in scene.assets:
                statuses.append(
                    AssetAcquisitionStatus(
                        asset_key=norm_key,
                        status="failed",
                        error_message=f"Asset key '{norm_key}' not available in scene STAC metadata",
                    )
                )
                failed_count += 1
                continue

            asset_info = scene.assets[norm_key]
            rel_path = f"scenes/{db_scene_id}/assets/{norm_key}.tif"
            if norm_key == "thumbnail":
                rel_path = f"scenes/{db_scene_id}/assets/{norm_key}.jpg"

            # Check if already present on disk with valid record
            existing_rec = existing_assets.get(norm_key)
            if existing_rec and existing_rec.status == "downloaded" and self.storage.exists(rel_path):
                # Check file size
                actual_size = self.storage.get_size(rel_path)
                if actual_size > 0:
                    statuses.append(
                        AssetAcquisitionStatus(
                            asset_key=norm_key,
                            status="already_present",
                            size_bytes=actual_size,
                            sha256=existing_rec.sha256,
                            local_path=rel_path,
                        )
                    )
                    already_present_count += 1
                    continue

            # Stream download with atomic file replacement
            logger.info("Downloading asset '%s' from %s", norm_key, asset_info.remote_url)
            try:
                size_bytes, sha256_hash = await self._stream_download_to_safe_path(
                    asset_info.remote_url, rel_path
                )

                # Update or create SatelliteAsset in DB
                if existing_rec:
                    existing_rec.local_path = rel_path
                    existing_rec.file_size_bytes = size_bytes
                    existing_rec.sha256 = sha256_hash
                    existing_rec.status = "downloaded"
                    existing_rec.downloaded_at = datetime.now(timezone.utc)
                    self.db.commit()
                else:
                    new_asset = SatelliteAssetCreate(
                        scene_id=db_scene_id,
                        asset_key=norm_key,
                        asset_type=asset_info.asset_type or "raster_band",
                        remote_url=asset_info.remote_url,
                        local_path=rel_path,
                        mime_type=asset_info.mime_type,
                        file_size_bytes=size_bytes,
                        sha256=sha256_hash,
                        status="downloaded",
                    )
                    created_asset = self.asset_repo.create(new_asset)
                    created_asset.downloaded_at = datetime.now(timezone.utc)
                    self.db.commit()

                statuses.append(
                    AssetAcquisitionStatus(
                        asset_key=norm_key,
                        status="downloaded",
                        size_bytes=size_bytes,
                        sha256=sha256_hash,
                        local_path=rel_path,
                    )
                )
                downloaded_count += 1

            except Exception as exc:
                logger.error("Download failed for asset '%s': %s", norm_key, exc)
                if existing_rec:
                    existing_rec.status = "failed"
                    self.db.commit()
                statuses.append(
                    AssetAcquisitionStatus(
                        asset_key=norm_key,
                        status="failed",
                        error_message=str(exc),
                    )
                )
                failed_count += 1

        # Update scene status
        total_success = downloaded_count + already_present_count
        if failed_count == 0 and total_success > 0:
            db_scene.status = "downloaded"
        elif total_success > 0:
            db_scene.status = "partial"
        else:
            db_scene.status = "failed"
        self.db.commit()

        overall_status = "completed" if failed_count == 0 else ("partial" if total_success > 0 else "failed")

        return SceneAcquisitionResponse(
            scene_id=db_scene_id,
            external_scene_id=scene.external_scene_id,
            status=overall_status,
            downloaded_assets=downloaded_count,
            failed_assets=failed_count,
            already_present_assets=already_present_count,
            assets=statuses,
        )

    async def _stream_download_to_safe_path(self, remote_url: str, rel_path: str) -> tuple[int, str]:
        target = self.storage.resolve_safe_path(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        hasher = hashlib.sha256()
        total_size = 0

        # Atomic download to temporary file in same folder
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, mode="wb") as f:
                temp_file = Path(f.name)
                async for chunk in self.provider.stream_asset_bytes(remote_url):
                    if chunk:
                        f.write(chunk)
                        hasher.update(chunk)
                        total_size += len(chunk)
                f.flush()
                os.fsync(f.fileno())

            # Atomic move
            shutil.move(str(temp_file), str(target))
            temp_file = None
            return total_size, hasher.hexdigest()
        finally:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
