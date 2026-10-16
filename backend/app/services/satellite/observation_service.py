import asyncio
import hashlib
import json
import logging
import math
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import settings
from app.db.models.water_body import WaterBody
from app.db.models.satellite_observation import SatelliteObservation
from app.db.repositories.water_body_repository import WaterBodyRepository
from app.db.repositories.satellite_observation_repository import SatelliteObservationRepository
from app.schemas.satellite_observation import (
    SatelliteObservationCreate,
    SatelliteObservationRead,
    VisualDataFetchRequest,
    VisualDataFetchResponse,
    AvailableObservationItem,
    AvailableObservationsResponse,
    FetchSelectedVisualDataRequest,
    VisualAcquisitionJobResponse,
    ObservationTimelineItem,
    IndicatorPlaceholder,
    TemporalAnalysisResponse,
)
from app.services.satellite.base import SatelliteProvider
from app.services.satellite.providers.stac import EarthSearchSTACProvider
from app.services.satellite.models import NormalizedScene
from app.services.raster.renderer import RGBRenderer
from app.services.storage_service import LocalStorageService, storage_service
from app.services.satellite.job_manager import job_manager, VisualAcquisitionJobManager

logger = logging.getLogger("jalnetra.satellite.observation_service")


class ObservationServiceError(Exception):
    def __init__(self, message: str, code: str = "OBSERVATION_SERVICE_ERROR"):
        super().__init__(message)
        self.code = code
        self.message = message


class SatelliteObservationService:
    """
    Water-body-centric time-series satellite observation service.
    Orchestrates targeted visual RGB data acquisition, temporal distribution,
    AOI clipping, and storage optimization.
    """

    # In-memory STAC scene cache with 10-minute TTL: (timestamp, List[NormalizedScene])
    _stac_scene_cache: Dict[str, Tuple[float, List[NormalizedScene]]] = {}

    def __init__(
        self,
        db: Session,
        provider: Optional[SatelliteProvider] = None,
        storage: Optional[LocalStorageService] = None,
        data_dir: Optional[Path] = None,
        jobs: Optional[VisualAcquisitionJobManager] = None,
    ):
        self.db = db
        self.provider = provider or EarthSearchSTACProvider()
        self.storage = storage or storage_service
        self.wb_repo = WaterBodyRepository(db)
        self.obs_repo = SatelliteObservationRepository(db)
        self._custom_data_dir = data_dir
        self.jobs = jobs or job_manager

    @property
    def data_dir(self) -> Path:
        return self._custom_data_dir or settings.resolved_data_dir

    @staticmethod
    def get_cloud_quality_label(cloud_pct: float) -> str:
        """Categorizes scene-level cloud percentage into clear UI labels."""
        if cloud_pct <= 10.0:
            return "VERY CLEAR"
        elif cloud_pct <= 25.0:
            return "CLEAR"
        elif cloud_pct <= 40.0:
            return "ACCEPTABLE"
        return "HIGH CLOUD"

    def _get_water_body_or_404(self, water_body_id: str) -> WaterBody:
        wb = self.wb_repo.get_by_id(water_body_id)
        if not wb:
            raise ObservationServiceError(
                f"Water body with ID '{water_body_id}' not found.",
                code="WATER_BODY_NOT_FOUND",
            )
        return wb

    def _get_water_body_aoi_and_crop_bounds(
        self, wb: WaterBody, padding_pct: float = 10.0
    ) -> Tuple[List[float], Tuple[float, float, float, float], Optional[Dict]]:
        """
        Derives bounding box, padded crop bounds (west, south, east, north),
        and geometry dictionary for a water body.
        """
        w, s, e, n = wb.min_lon, wb.min_lat, wb.max_lon, wb.max_lat
        geom_dict = None

        if wb.geometry_geojson:
            try:
                parsed = json.loads(wb.geometry_geojson)
                if parsed.get("type") in ("Polygon", "MultiPolygon", "Point"):
                    geom_dict = parsed
                    if w is None or s is None or e is None or n is None:
                        from shapely.geometry import shape
                        w, s, e, n = shape(parsed).bounds
            except Exception:
                pass

        if w is None or s is None or e is None or n is None:
            if wb.centroid_lon is not None and wb.centroid_lat is not None:
                # Minimal 0.02 deg box around centroid
                w = wb.centroid_lon - 0.01
                s = wb.centroid_lat - 0.01
                e = wb.centroid_lon + 0.01
                n = wb.centroid_lat + 0.01
            else:
                raise ObservationServiceError(
                    f"Water body '{wb.name}' lacks spatial coordinates.",
                    code="MISSING_GEOMETRY",
                )

        # Apply padding for visual context
        pad_factor = max(padding_pct, 1.0) / 100.0
        span_x = max(e - w, 0.002)
        span_y = max(n - s, 0.002)
        pad_x = span_x * pad_factor
        pad_y = span_y * pad_factor

        crop_bounds = (w - pad_x, s - pad_y, e + pad_x, n + pad_y)
        bbox = [w, s, e, n]
        return bbox, crop_bounds, geom_dict

    async def get_available_observations(
        self,
        water_body_id: str,
        from_date: str,
        to_date: str,
        max_cloud: float = 40.0,
        include_high_cloud: bool = False,
        sort: str = "newest",
    ) -> AvailableObservationsResponse:
        """
        Performs a metadata/STAC search ONLY for available observations across the date range.
        Does NOT download bands, does NOT crop rasters, does NOT store images.
        Filters to cloud_cover_percent <= max_cloud (default 40%) unless include_high_cloud is True.
        """
        wb = self._get_water_body_or_404(water_body_id)

        try:
            start_dt = datetime.strptime(from_date.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end_dt = datetime.strptime(to_date.strip(), "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError:
            raise ObservationServiceError(
                f"Dates must be in YYYY-MM-DD format (got from_date='{from_date}', to_date='{to_date}')",
                code="INVALID_DATE_FORMAT",
            )

        if start_dt > end_dt:
            raise ObservationServiceError(
                f"from_date ({from_date}) must be before or equal to to_date ({to_date}).",
                code="INVALID_DATE_RANGE",
            )

        bbox, _, geom_dict = self._get_water_body_aoi_and_crop_bounds(wb)

        # Check cache (10 min TTL)
        cache_key = f"{wb.id}:{from_date}:{to_date}"
        now = time.time()
        scenes: Optional[List[NormalizedScene]] = None
        if cache_key in self._stac_scene_cache:
            ts, cached_scenes = self._stac_scene_cache[cache_key]
            if (now - ts) < 600.0:
                scenes = cached_scenes

        if scenes is None:
            logger.info("STAC query for '%s' metadata between %s and %s", wb.name, from_date, to_date)
            try:
                scenes = await self.provider.search_scenes(
                    geometry=geom_dict,
                    bbox=bbox,
                    start_date=start_dt,
                    end_date=end_dt,
                    max_cloud_cover=100.0,  # capture all so high-cloud toggle can inspect them
                    limit=100,
                )
                self._stac_scene_cache[cache_key] = (now, scenes)
            except Exception as exc:
                logger.error("STAC search error for '%s': %s", wb.name, exc)
                raise ObservationServiceError(
                    f"Failed to query satellite archive: {str(exc)}",
                    code="STAC_SEARCH_ERROR",
                )

        # Only scenes with RGB bands
        rgb_scenes = [
            s for s in scenes
            if "B04" in s.assets and "B03" in s.assets and "B02" in s.assets
        ]

        # Deduplicate scenes by external_scene_id to prevent exact scene repetition
        seen_scene_ids = set()
        deduped_rgb_scenes = []
        for s in rgb_scenes:
            if s.external_scene_id not in seen_scene_ids:
                seen_scene_ids.add(s.external_scene_id)
                deduped_rgb_scenes.append(s)

        items: List[AvailableObservationItem] = []
        for s in deduped_rgb_scenes:
            cloud = float(s.cloud_cover_percent or 0.0)
            is_high_cloud = cloud > max_cloud
            quality_label = self.get_cloud_quality_label(cloud)

            # Skip high cloud scenes if user hasn't explicitly requested them
            if is_high_cloud and not include_high_cloud:
                continue

            # Check if observation already exists in DB & on disk
            existing_obs = self.obs_repo.get_by_water_body_and_scene(wb.id, s.external_scene_id)
            already_acquired = False
            existing_obs_id = None
            existing_img_url = None
            file_size = None

            if existing_obs and existing_obs.local_visual_path:
                full_path = self.data_dir / existing_obs.local_visual_path
                if full_path.exists():
                    already_acquired = True
                    existing_obs_id = existing_obs.id
                    existing_img_url = f"/api/v1/water-bodies/{wb.id}/observations/{existing_obs.id}/image"
                    file_size = existing_obs.file_size_bytes

            platform = (
                "Sentinel-2A" if s.external_scene_id.startswith("S2A")
                else "Sentinel-2B" if s.external_scene_id.startswith("S2B")
                else "Sentinel-2"
            )

            item = AvailableObservationItem(
                observation_id=s.external_scene_id,
                scene_id=s.external_scene_id,
                id=s.external_scene_id,
                satellite="Sentinel-2",
                platform=platform,
                sensing_date=s.sensing_start,
                sensing_date_str=s.sensing_start.strftime("%Y-%m-%d"),
                cloud_cover_percent=round(cloud, 2),
                quality_label=quality_label,
                is_high_cloud=is_high_cloud,
                already_acquired=already_acquired,
                is_already_available=already_acquired,
                existing_observation_id=existing_obs_id,
                existing_image_url=existing_img_url,
                file_size_bytes=file_size,
            )
            items.append(item)

        # Sorting
        if sort == "oldest":
            items.sort(key=lambda x: x.sensing_date)
        elif sort == "lowest_cloud":
            items.sort(key=lambda x: (x.cloud_cover_percent, -x.sensing_date.timestamp()))
        else:  # "newest" default
            items.sort(key=lambda x: x.sensing_date, reverse=True)

        return AvailableObservationsResponse(
            water_body_id=wb.id,
            water_body_name=wb.name,
            from_date=from_date,
            to_date=to_date,
            max_cloud_cover=max_cloud,
            include_high_cloud=include_high_cloud,
            total_found=len(items),
            items=items,
        )

    async def _acquire_single_observation(
        self,
        wb: WaterBody,
        scene: NormalizedScene,
        crop_bounds: Tuple[float, float, float, float],
        wb_storage_dir: Path,
        job_id: Optional[str] = None,
        current_index: int = 1,
        total: int = 1,
    ) -> Tuple[Optional[SatelliteObservationRead], bool, Optional[str]]:
        """
        Acquires and processes a single visual observation.
        Returns: (observation_dto, is_reused, error_message)
        """
        t0 = time.perf_counter()

        # 1. Check if already present locally
        existing_obs = self.obs_repo.get_by_water_body_and_scene(wb.id, scene.external_scene_id)
        if existing_obs and existing_obs.local_visual_path:
            full_path = self.data_dir / existing_obs.local_visual_path
            if full_path.exists():
                logger.info("Reusing existing observation %s for water body %s", existing_obs.id, wb.name)
                dto = SatelliteObservationRead.model_validate(existing_obs)
                dto.image_url = f"/api/v1/water-bodies/{wb.id}/observations/{existing_obs.id}/image"
                return dto, True, None

        obs_dir = wb_storage_dir / scene.external_scene_id
        obs_dir.mkdir(parents=True, exist_ok=True)
        rgb_jpg_path = obs_dir / "rgb.jpg"
        meta_json_path = obs_dir / "metadata.json"

        # Update stage
        if job_id:
            pct = int(round(((current_index - 0.7) / total) * 100))
            await self.jobs.update_job(
                job_id,
                current_stage="READING AOI",
                current_scene_id=scene.external_scene_id,
                current_index=current_index,
                percent=pct,
                details=f"Reading AOI raster data for {scene.sensing_start.strftime('%d %b %Y')}",
            )

        render_res = None
        t_read_start = time.perf_counter()

        # Attempt direct windowed range reading from remote COG URLs
        b04_url = scene.assets["B04"].remote_url
        b03_url = scene.assets["B03"].remote_url
        b02_url = scene.assets["B02"].remote_url

        try:
            logger.info("Performing windowed range read for scene %s", scene.external_scene_id)
            render_res = RGBRenderer.render_rgb(
                red_path=b04_url,
                green_path=b03_url,
                blue_path=b02_url,
                output_png_path=rgb_jpg_path,
                crop_bounds=crop_bounds,
                max_dimension=1024,
                raise_on_unusable=False,
            )
        except Exception as range_exc:
            logger.warning(
                "Direct range read failed for %s (%s). Falling back to streaming download.",
                scene.external_scene_id, range_exc,
            )
            # Fallback to streaming download of bands into temporary directory
            try:
                with tempfile.TemporaryDirectory(prefix="jalnetra_rgb_fallback_") as tmp_dir_str:
                    tmp_dir = Path(tmp_dir_str)
                    b04_tmp = tmp_dir / "B04.tif"
                    b03_tmp = tmp_dir / "B03.tif"
                    b02_tmp = tmp_dir / "B02.tif"

                    await self._download_band_asset(b04_url, b04_tmp)
                    await self._download_band_asset(b03_url, b03_tmp)
                    await self._download_band_asset(b02_url, b02_tmp)

                    render_res = RGBRenderer.render_rgb(
                        red_path=b04_tmp,
                        green_path=b03_tmp,
                        blue_path=b02_tmp,
                        output_png_path=rgb_jpg_path,
                        crop_bounds=crop_bounds,
                        max_dimension=1024,
                        raise_on_unusable=False,
                    )
            except Exception as stream_exc:
                err_msg = f"Failed to acquire raster bands: {str(stream_exc)}"
                logger.error("Acquisition failure for %s: %s", scene.external_scene_id, stream_exc)
                return None, False, err_msg

        t_read_end = time.perf_counter()

        if job_id:
            pct = int(round(((current_index - 0.3) / total) * 100))
            await self.jobs.update_job(
                job_id,
                current_stage="COMPOSITING RGB",
                current_scene_id=scene.external_scene_id,
                percent=pct,
                details=f"Compositing & validating natural color visual output ({current_index}/{total})",
            )

        # Image Quality Validation
        if not render_res.get("quality_valid", True):
            reason = render_res.get("quality_reason", "Unusable output")
            logger.warning("Observation %s rejected: %s", scene.external_scene_id, reason)
            # Clean up generated file if invalid
            if rgb_jpg_path.exists():
                try:
                    rgb_jpg_path.unlink()
                except Exception:
                    pass
            return None, False, f"UNUSABLE VISUAL OUTPUT: {reason}"

        # Stage: SAVING
        if job_id:
            pct = int(round(((current_index - 0.1) / total) * 100))
            await self.jobs.update_job(
                job_id,
                current_stage="SAVING",
                current_scene_id=scene.external_scene_id,
                percent=pct,
                details=f"Saving observation metadata and registering ({current_index}/{total})",
            )

        t_save_start = time.perf_counter()
        file_size = rgb_jpg_path.stat().st_size
        sha256_hash = hashlib.sha256(rgb_jpg_path.read_bytes()).hexdigest()

        rel_visual_path = f"water_bodies/{wb.id}/observations/{scene.external_scene_id}/rgb.jpg"
        total_time_ms = round((time.perf_counter() - t0) * 1000)
        read_time_ms = round((t_read_end - t_read_start) * 1000)

        meta_data = {
            "water_body_id": wb.id,
            "water_body_name": wb.name,
            "external_scene_id": scene.external_scene_id,
            "sensing_date": scene.sensing_start.isoformat(),
            "cloud_cover_percent": scene.cloud_cover_percent,
            "quality_label": self.get_cloud_quality_label(scene.cloud_cover_percent or 0.0),
            "crop_bounds": list(crop_bounds),
            "image_width": render_res["width"],
            "image_height": render_res["height"],
            "file_size_bytes": file_size,
            "sha256": sha256_hash,
            "quality_metrics": render_res.get("quality_metrics", {}),
            "timing_metrics": {
                "raster_read_and_composite_ms": read_time_ms,
                "total_observation_ms": total_time_ms,
            },
        }
        meta_json_path.write_text(json.dumps(meta_data, indent=2), encoding="utf-8")

        # Persist in DB (update existing or create new)
        if existing_obs:
            existing_obs.aoi_bounds = json.dumps(list(crop_bounds))
            existing_obs.aoi_geojson = wb.geometry_geojson
            existing_obs.local_visual_path = rel_visual_path
            existing_obs.image_width = render_res["width"]
            existing_obs.image_height = render_res["height"]
            existing_obs.file_size_bytes = file_size
            existing_obs.sha256 = sha256_hash
            existing_obs.status = "ready"
            existing_obs.metadata_json = json.dumps(meta_data)
            db_obs = self.obs_repo.update(existing_obs)
        else:
            obs_create = SatelliteObservationCreate(
                water_body_id=wb.id,
                satellite="Sentinel-2",
                provider=self.provider.name,
                collection=self.provider.collection,
                external_scene_id=scene.external_scene_id,
                sensing_date=scene.sensing_start,
                cloud_cover_percent=scene.cloud_cover_percent,
                aoi_bounds=json.dumps(list(crop_bounds)),
                aoi_geojson=wb.geometry_geojson,
                local_visual_path=rel_visual_path,
                image_width=render_res["width"],
                image_height=render_res["height"],
                file_size_bytes=file_size,
                sha256=sha256_hash,
                derived_water_area_sq_km=None,  # Not fake area; segmentation pending
                status="ready",
                metadata_json=json.dumps(meta_data),
            )
            db_obs = self.obs_repo.create(obs_create)

        dto = SatelliteObservationRead.model_validate(db_obs)
        dto.image_url = f"/api/v1/water-bodies/{wb.id}/observations/{db_obs.id}/image"

        logger.info(
            "Observation %s acquired in %d ms (size: %d bytes, dim: %dx%d)",
            scene.external_scene_id, total_time_ms, file_size, render_res["width"], render_res["height"]
        )
        return dto, False, None

    async def fetch_selected_observations(
        self,
        water_body_id: str,
        observation_ids: List[str],
        job_id: Optional[str] = None,
    ) -> VisualAcquisitionJobResponse:
        """
        Executes acquisition for explicitly selected observation IDs.
        Provides stage-by-stage real-time progress via job_manager.
        Handles partial failures gracefully without aborting the entire request.
        """
        wb = self._get_water_body_or_404(water_body_id)

        # Enforce max 20 observations
        if not observation_ids or len(observation_ids) == 0:
            raise ObservationServiceError("At least one observation must be selected.", code="EMPTY_SELECTION")
        if len(observation_ids) > 20:
            raise ObservationServiceError(
                "Maximum 20 observations can be fetched at once. Please reduce your selection.",
                code="EXCESSIVE_SELECTION",
            )

        total = len(observation_ids)

        # Create or update job
        if not job_id:
            job_resp = await self.jobs.create_job(
                water_body_id=wb.id,
                total=total,
                initial_message=f"Starting acquisition of {total} selected observations for {wb.name}",
            )
            job_id = job_resp.job_id

        await self.jobs.update_job(
            job_id,
            status="running",
            current_stage="SEARCHING",
            percent=5,
            details="Resolving target observation scene metadata...",
        )

        bbox, crop_bounds, geom_dict = self._get_water_body_aoi_and_crop_bounds(wb)
        wb_storage_dir = self.data_dir / "water_bodies" / wb.id / "observations"
        wb_storage_dir.mkdir(parents=True, exist_ok=True)

        # Resolve scenes for the given IDs
        # 1. Check in-memory cache
        scenes_map: Dict[str, NormalizedScene] = {}
        for _, (_, cached_list) in self._stac_scene_cache.items():
            for sc in cached_list:
                if sc.external_scene_id in observation_ids:
                    scenes_map[sc.external_scene_id] = sc

        # 2. For missing scenes, query STAC directly
        missing_ids = [sid for sid in observation_ids if sid not in scenes_map]
        if missing_ids:
            # Query STAC over wide date range or specific dates if needed
            logger.info("Querying STAC for %d missing scene IDs", len(missing_ids))
            try:
                # 3 years window to catch historical selections
                now_utc = datetime.now(timezone.utc)
                start_utc = datetime(2020, 1, 1, tzinfo=timezone.utc)
                stac_scenes = await self.provider.search_scenes(
                    geometry=geom_dict,
                    bbox=bbox,
                    start_date=start_utc,
                    end_date=now_utc,
                    max_cloud_cover=100.0,
                    limit=100,
                )
                for sc in stac_scenes:
                    if sc.external_scene_id in missing_ids:
                        scenes_map[sc.external_scene_id] = sc
            except Exception as exc:
                logger.warning("Could not refresh STAC for missing IDs: %s", exc)

        completed_count = 0
        reused_count = 0
        failed_count = 0
        acquired_dtos: List[SatelliteObservationRead] = []

        for idx, scene_id in enumerate(observation_ids, start=1):
            pct_start = int(round(((idx - 1) / total) * 100))
            await self.jobs.update_job(
                job_id,
                current_index=idx,
                current_scene_id=scene_id,
                current_stage="ACQUIRING",
                percent=pct_start,
                details=f"Processing observation {idx} of {total} ({scene_id})...",
            )
            scene = scenes_map.get(scene_id)
            if not scene:
                # Check if it was already an existing observation in the DB
                existing_obs = self.obs_repo.get_by_water_body_and_scene(wb.id, scene_id)
                if existing_obs and existing_obs.local_visual_path:
                    full_path = self.data_dir / existing_obs.local_visual_path
                    if full_path.exists():
                        reused_count += 1
                        dto = SatelliteObservationRead.model_validate(existing_obs)
                        dto.image_url = f"/api/v1/water-bodies/{wb.id}/observations/{existing_obs.id}/image"
                        acquired_dtos.append(dto)
                        pct = int(round((idx / total) * 100))
                        await self.jobs.update_job(
                            job_id,
                            completed=completed_count,
                            reused=reused_count,
                            failed=failed_count,
                            current_index=idx,
                            current_scene_id=scene_id,
                            current_stage="REUSING",
                            percent=pct,
                            details=f"Observation {scene_id} already available locally",
                            add_result=dto,
                        )
                        continue

                # Scene not found in archive or database
                failed_count += 1
                err_dict = {
                    "scene_id": scene_id,
                    "observation_id": scene_id,
                    "error": f"Observation '{scene_id}' was not found for water body '{wb.name}'."
                }
                pct = int(round((idx / total) * 100))
                await self.jobs.update_job(
                    job_id,
                    completed=completed_count,
                    reused=reused_count,
                    failed=failed_count,
                    current_index=idx,
                    current_scene_id=scene_id,
                    current_stage="FAILED",
                    percent=pct,
                    add_error=err_dict,
                )
                continue

            # Process single observation
            dto, is_reused, error_msg = await self._acquire_single_observation(
                wb=wb,
                scene=scene,
                crop_bounds=crop_bounds,
                wb_storage_dir=wb_storage_dir,
                job_id=job_id,
                current_index=idx,
                total=total,
            )

            pct = int(round((idx / total) * 100))

            if dto:
                if is_reused:
                    reused_count += 1
                else:
                    completed_count += 1
                acquired_dtos.append(dto)
                await self.jobs.update_job(
                    job_id,
                    completed=completed_count,
                    reused=reused_count,
                    failed=failed_count,
                    current_index=idx,
                    current_scene_id=scene_id,
                    current_stage="COMPLETED",
                    percent=pct,
                    details=f"Observation {scene_id} processed successfully",
                    add_result=dto,
                )
            else:
                failed_count += 1
                err_dict = {"scene_id": scene_id, "error": error_msg or "Unknown error"}
                await self.jobs.update_job(
                    job_id,
                    completed=completed_count,
                    reused=reused_count,
                    failed=failed_count,
                    current_index=idx,
                    current_scene_id=scene_id,
                    current_stage="FAILED",
                    percent=pct,
                    details=f"Observation {scene_id} failed: {error_msg}",
                    add_error=err_dict,
                )

        # Finalize job status
        final_status = "completed" if (completed_count + reused_count) > 0 or failed_count == 0 else "failed"
        final_stage = "COMPLETED" if final_status == "completed" else "FAILED"
        final_msg = (
            f"Successfully acquired {completed_count} and reused {reused_count} visual observations "
            f"({failed_count} failed)."
        )

        final_job = await self.jobs.update_job(
            job_id,
            status=final_status,
            current_stage=final_stage,
            percent=100,
            details="All selected observations processed.",
            message=final_msg,
        )
        return final_job

    async def fetch_visual_data(
        self, water_body_id: str, request: VisualDataFetchRequest
    ) -> VisualDataFetchResponse:
        """
        Legacy fetch API for backward compatibility.
        Distributes request.image_count across the date range and fetches them.
        """
        wb = self._get_water_body_or_404(water_body_id)
        start_dt = datetime.strptime(request.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(request.to_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )

        if start_dt > end_dt:
            raise ObservationServiceError(
                f"from_date ({request.from_date}) must be before or equal to to_date ({request.to_date}).",
                code="INVALID_DATE_RANGE",
            )

        avail_resp = await self.get_available_observations(
            water_body_id=wb.id,
            from_date=request.from_date,
            to_date=request.to_date,
            max_cloud=100.0,
            include_high_cloud=True,
            sort="newest",
        )

        target_count = min(request.image_count, 20)
        items = avail_resp.items
        selected_ids: List[str] = []

        if len(items) <= target_count:
            selected_ids = [it.scene_id for it in items]
        else:
            # Uniform bin sampling
            span = max(end_dt.timestamp() - start_dt.timestamp(), 1.0)
            bin_size = span / target_count
            used = set()
            for k in range(target_count):
                t_target = start_dt.timestamp() + (k + 0.5) * bin_size
                candidates = [it for it in items if it.scene_id not in used]
                if not candidates:
                    break
                best = min(candidates, key=lambda it: abs(it.sensing_date.timestamp() - t_target))
                used.add(best.scene_id)
                selected_ids.append(best.scene_id)

        job_resp = await self.fetch_selected_observations(wb.id, selected_ids)

        if avail_resp.total_found == 0:
            msg = f"No Sentinel-2 observations found for '{wb.name}' between {request.from_date} and {request.to_date}."
        elif avail_resp.total_found < target_count:
            msg = (
                f"Only {avail_resp.total_found} observations were available in the selected period "
                f"(requested {target_count}). Acquired {job_resp.completed}, reused {job_resp.reused}."
            )
        else:
            msg = job_resp.message

        return VisualDataFetchResponse(
            water_body_id=wb.id,
            water_body_name=wb.name,
            from_date=request.from_date,
            to_date=request.to_date,
            requested_count=request.image_count,
            available_count=avail_resp.total_found,
            acquired_count=job_resp.completed,
            reused_count=job_resp.reused,
            failed_count=job_resp.failed,
            message=msg,
            observations=job_resp.results,
        )

    async def _download_band_asset(self, remote_url: str, dest_path: Path) -> None:
        """Streams a single band asset directly to a file (used as fallback)."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            async for chunk in self.provider.stream_asset_bytes(remote_url):
                f.write(chunk)

    def list_observations_for_water_body(
        self, water_body_id: str, from_date: Optional[str] = None, to_date: Optional[str] = None
    ) -> List[SatelliteObservationRead]:
        wb = self._get_water_body_or_404(water_body_id)
        start_dt = (
            datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if from_date
            else None
        )
        end_dt = (
            datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            if to_date
            else None
        )

        observations = self.obs_repo.list_for_water_body(wb.id, start_date=start_dt, end_date=end_dt)
        results = []
        for obs in observations:
            dto = SatelliteObservationRead.model_validate(obs)
            dto.image_url = f"/api/v1/water-bodies/{wb.id}/observations/{obs.id}/image"
            results.append(dto)
        return results

    def get_observation_file_path(self, water_body_id: str, observation_id: str) -> Path:
        """
        Securely resolves the visual image file path for an observation,
        guaranteeing water body ownership and path traversal prevention.
        """
        obs = self.obs_repo.get_by_id(observation_id)
        if not obs or obs.water_body_id != water_body_id:
            raise ObservationServiceError(
                f"Observation '{observation_id}' not found for water body '{water_body_id}'.",
                code="OBSERVATION_NOT_FOUND",
            )

        if not obs.local_visual_path:
            raise ObservationServiceError("Observation has no local visual asset path.", code="ASSET_MISSING")

        clean_rel = Path(obs.local_visual_path)
        if ".." in clean_rel.parts:
            raise ObservationServiceError("Illegal path traversal detected.", code="SECURITY_VIOLATION")

        full_path = (self.data_dir / clean_rel).resolve()
        if not str(full_path).startswith(str(self.data_dir.resolve())):
            raise ObservationServiceError("Path escapes data storage root.", code="SECURITY_VIOLATION")

        if not full_path.exists():
            raise ObservationServiceError(
                f"Local visual asset file missing from disk: {full_path.name}",
                code="FILE_NOT_FOUND",
            )
        return full_path

    def get_filtered_observation_image(
        self, water_body_id: str, observation_id: str, filter_type: str = "natural"
    ) -> Tuple[Optional[Path], Optional[str], Optional[bytes]]:
        """
        Returns (file_path, media_type, raw_bytes).
        If raw_bytes is provided (e.g. for SVG messages), it should be served directly.
        Otherwise, file_path should be served with media_type.
        """
        rgb_path = self.get_observation_file_path(water_body_id, observation_id)
        obs_dir = rgb_path.parent
        filter_lower = (filter_type or "natural").lower().strip()

        if filter_lower in ("natural", "true_color", "rgb"):
            return rgb_path, "image/jpeg", None

        if filter_lower == "water_emphasis":
            target_path = obs_dir / "rgb_water_emphasis.jpg"
            if not target_path.exists():
                try:
                    from PIL import Image, ImageEnhance
                    import numpy as np
                    with Image.open(rgb_path) as im:
                        rgb = im.convert("RGB")
                        arr = np.array(rgb, dtype=np.float32)
                        r = arr[:, :, 0]
                        g = arr[:, :, 1]
                        b = arr[:, :, 2]
                        # Water reflectance proxy: high B & G, low R
                        water_mask = (b > r * 0.95) & (g > r * 0.9)
                        # Boost blue and green in potential water pixels
                        arr[:, :, 2] = np.clip(np.where(water_mask, b * 1.35, b * 1.05), 0, 255)
                        arr[:, :, 1] = np.clip(np.where(water_mask, g * 1.2, g * 1.02), 0, 255)
                        arr[:, :, 0] = np.clip(np.where(water_mask, r * 0.75, r * 0.95), 0, 255)
                        enhanced_im = Image.fromarray(arr.astype(np.uint8))
                        enhanced_im = ImageEnhance.Contrast(enhanced_im).enhance(1.25)
                        enhanced_im.save(target_path, "JPEG", quality=85)
                except Exception as exc:
                    logger.warning("Could not generate water emphasis image: %s", exc)
                    return rgb_path, "image/jpeg", None
            return target_path, "image/jpeg", None

        if filter_lower == "contrast":
            target_path = obs_dir / "rgb_contrast.jpg"
            if not target_path.exists():
                try:
                    from PIL import Image, ImageEnhance
                    with Image.open(rgb_path) as im:
                        enh = ImageEnhance.Contrast(im).enhance(1.45)
                        enh = ImageEnhance.Color(enh).enhance(1.3)
                        enh.save(target_path, "JPEG", quality=85)
                except Exception as exc:
                    logger.warning("Could not generate contrast image: %s", exc)
                    return rgb_path, "image/jpeg", None
            return target_path, "image/jpeg", None

        # For spectral bands: false_color (B08, B04, B03), nir (B08), swir (B11, B12)
        band_file_map = {
            "false_color": ("Color Infrared (NIR/Red/Green)", "NIR Band (B08)"),
            "nir": ("Near-Infrared (B08)", "NIR Band (B08)"),
            "swir": ("Short-Wave Infrared (B11/B12)", "SWIR Bands (B11/B12)"),
        }
        band_title, missing_band_name = band_file_map.get(
            filter_lower, ("Spectral Filter", "Required Band")
        )

        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600" width="100%" height="100%">
  <rect width="800" height="600" fill="#090d16"/>
  <rect x="24" y="24" width="752" height="552" rx="16" fill="#0f172a" stroke="#334155" stroke-width="2"/>
  <circle cx="400" cy="200" r="54" fill="#1e293b" stroke="#38bdf8" stroke-width="2"/>
  <path d="M375 200 h50 M400 175 v50 M380 185 l40 30 M380 215 l40 -30" stroke="#0ea5e9" stroke-width="2.5" stroke-linecap="round"/>
  <text x="400" y="300" text-anchor="middle" fill="#f8fafc" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" font-size="22" font-weight="700">
    {band_title} Not Acquired
  </text>
  <text x="400" y="340" text-anchor="middle" fill="#94a3b8" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" font-size="15">
    Targeted visual acquisition fetched natural RGB bands (B04, B03, B02).
  </text>
  <text x="400" y="370" text-anchor="middle" fill="#94a3b8" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" font-size="15">
    {missing_band_name} was omitted to keep observation downloads fast &amp; lightweight.
  </text>
  <g transform="translate(260, 420)">
    <rect width="280" height="40" rx="8" fill="#1e293b" stroke="#0284c7" stroke-dasharray="4 4" stroke-width="1.5"/>
    <text x="140" y="25" text-anchor="middle" fill="#38bdf8" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif" font-size="13" font-weight="600" letter-spacing="0.5">
      LEVEL 2 SPECTRAL ANALYSIS
    </text>
  </g>
</svg>"""
        return None, "image/svg+xml", svg_content.encode("utf-8")

    def get_temporal_analysis(
        self, water_body_id: str, from_date: Optional[str] = None, to_date: Optional[str] = None
    ) -> TemporalAnalysisResponse:
        import math
        wb = self._get_water_body_or_404(water_body_id)
        obs_list = self.list_observations_for_water_body(wb.id, from_date=from_date, to_date=to_date)

        timeline_items: List[ObservationTimelineItem] = []
        prev_extent = None

        for obs in obs_list:
            extent = obs.derived_water_area_sq_km
            is_demo = False
            if extent is None and wb.area_sq_km and wb.area_sq_km > 0:
                # Deterministic demo extent around registered area:
                # Seasonal curve based on sensing date day-of-year (e.g. monsoon variation)
                doy = obs.sensing_date.timetuple().tm_yday
                seasonal_factor = 0.06 * math.sin((doy - 120) * 2 * math.pi / 365)
                # Small deterministic noise derived from external_scene_id
                h_val = (int(hashlib.md5(obs.external_scene_id.encode()).hexdigest()[:4], 16) % 100 - 50) / 2500.0
                demo_val = wb.area_sq_km * (0.94 + seasonal_factor + h_val)
                extent = round(max(demo_val, wb.area_sq_km * 0.4), 2)
                is_demo = True

            is_measured = obs.derived_water_area_sq_km is not None
            change = (extent - prev_extent) if (extent is not None and prev_extent is not None) else None
            quality = self.get_cloud_quality_label(obs.cloud_cover_percent or 0.0)

            # Ensure bounds and geojson are present
            bounds_val = obs.aoi_bounds
            if not bounds_val and wb.min_lon is not None:
                bounds_val = json.dumps([wb.min_lon, wb.min_lat, wb.max_lon, wb.max_lat])
            geojson_val = obs.aoi_geojson or wb.geometry_geojson
            if not geojson_val and bounds_val:
                try:
                    b = json.loads(bounds_val)
                    if isinstance(b, list) and len(b) == 4:
                        geojson_val = json.dumps({
                            "type": "Polygon",
                            "coordinates": [[
                                [b[0], b[1]],
                                [b[2], b[1]],
                                [b[2], b[3]],
                                [b[0], b[3]],
                                [b[0], b[1]],
                            ]]
                        })
                except Exception:
                    pass

            item = ObservationTimelineItem(
                id=obs.id,
                water_body_id=obs.water_body_id,
                external_scene_id=obs.external_scene_id,
                sensing_date=obs.sensing_date,
                sensing_date_str=obs.sensing_date.strftime("%Y-%m-%d"),
                cloud_cover_percent=round(obs.cloud_cover_percent, 1) if obs.cloud_cover_percent is not None else None,
                quality_label=quality,
                image_url=obs.image_url or f"/api/v1/water-bodies/{wb.id}/observations/{obs.id}/image",
                file_size_bytes=obs.file_size_bytes,
                image_width=obs.image_width,
                image_height=obs.image_height,
                water_extent_sq_km=round(extent, 2) if extent is not None else None,
                is_extent_measured=is_measured,
                is_demo_extent=is_demo,
                registered_area_sq_km=wb.area_sq_km,
                change_from_previous_sq_km=round(change, 2) if change is not None else None,
                aoi_bounds=bounds_val,
                aoi_geojson=geojson_val,
                status=obs.status,
            )
            timeline_items.append(item)
            if extent is not None:
                prev_extent = extent

        indicators = {
            "turbidity": IndicatorPlaceholder(
                id="turbidity",
                label="Turbidity / Sediment Proxy",
                description="Remote-sensing proxy reflecting suspended particulate matter and sediment scattering.",
                status="coming_soon",
                message="COMING IN ANALYSIS PHASE",
                unit="NDTI proxy",
            ),
            "chlorophyll": IndicatorPlaceholder(
                id="chlorophyll",
                label="Chlorophyll-a Proxy",
                description="Spectral index estimating photosynthetic pigment concentration in surface water.",
                status="coming_soon",
                message="COMING IN ANALYSIS PHASE",
                unit="NDCI proxy",
            ),
            "algae": IndicatorPlaceholder(
                id="algae",
                label="Algal Activity Proxy",
                description="Surface bloom and cyanobacterial reflectance anomaly detection.",
                status="coming_soon",
                message="COMING IN ANALYSIS PHASE",
                unit="FAI proxy",
            ),
            "anomaly": IndicatorPlaceholder(
                id="anomaly",
                label="Surface Spectral Anomaly",
                description="Detects statistical divergence relative to historical water-body reflectance baseline.",
                status="coming_soon",
                message="COMING IN ANALYSIS PHASE",
                unit="Z-score proxy",
            ),
        }

        min_date = timeline_items[0].sensing_date_str if timeline_items else None
        max_date = timeline_items[-1].sensing_date_str if timeline_items else None

        return TemporalAnalysisResponse(
            water_body_id=wb.id,
            water_body_name=wb.name,
            country=wb.country,
            area_sq_km=wb.area_sq_km,
            total_observations=len(timeline_items),
            from_date=min_date,
            to_date=max_date,
            timeline=timeline_items,
            indicators=indicators,
        )
