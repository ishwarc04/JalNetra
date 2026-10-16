import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import uuid
import numpy as np

from app.core.config import settings
from app.db.models.satellite_observation import SatelliteObservation
from app.db.models.water_body import WaterBody
from app.db.repositories.satellite_observation_repository import SatelliteObservationRepository
from app.db.repositories.water_body_repository import WaterBodyRepository
from app.services.spectral.models import (
    IndicatorType,
    QualityLevel,
    BandAvailabilityInfo,
    SpectralAnalysisResult,
    TimeSeriesSpectralResponse,
    MultiIndicatorSummary,
)
from app.services.spectral.band_loader import SpectralBandLoader
from app.services.spectral.cloud_mask import SCLCloudMasker
from app.services.spectral.aoi_processor import WaterBodyAOIProcessor
from app.services.spectral.statistics import SpectralStatistics
from app.services.spectral.indicators import (
    INDICATOR_REGISTRY,
    TurbidityIndicator,
    ChlorophyllIndicator,
    AlgalActivityIndicator,
    SpectralAnomalyIndicator,
)

logger = logging.getLogger("jalnetra.spectral.service")


class SpectralServiceError(Exception):
    def __init__(self, message: str, code: str = "SPECTRAL_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class SpectralAnalysisService:
    """
    On-demand, water-body-centric spectral analysis system for remote sensing proxies.
    Calculates NDTI, NDCI, FAI, and Anomaly restricted strictly to the water-body AOI.
    Caches all results and previews compactly.
    """

    def __init__(self, db_session, data_dir: Optional[Path] = None):
        self.db = db_session
        self.data_dir = data_dir or Path(settings.DATA_DIR)
        self.wb_repo = WaterBodyRepository(db_session)
        self.obs_repo = SatelliteObservationRepository(db_session)
        self.band_loader = SpectralBandLoader(self.data_dir)

    def _get_water_body_or_404(self, wb_id: str) -> WaterBody:
        wb = self.wb_repo.get_by_id(wb_id)
        if not wb:
            raise SpectralServiceError(f"Water body '{wb_id}' not found.", code="WATER_BODY_NOT_FOUND")
        return wb

    def _get_observation_or_404(self, wb_id: str, obs_id: str) -> SatelliteObservation:
        obs = self.obs_repo.get_by_id(obs_id)
        if not obs or obs.water_body_id != wb_id:
            raise SpectralServiceError(
                f"Observation '{obs_id}' not found for water body '{wb_id}'.",
                code="OBSERVATION_NOT_FOUND",
            )
        return obs

    def _get_spectral_cache_paths(self, wb_id: str, scene_id: str, indicator: str) -> Tuple[Path, Path]:
        obs_dir = self.data_dir / "water_bodies" / wb_id / "observations" / scene_id
        spectral_dir = obs_dir / "spectral"
        spectral_dir.mkdir(parents=True, exist_ok=True)
        result_json_path = spectral_dir / f"{indicator}_result.json"
        preview_png_path = spectral_dir / f"{indicator}_preview.png"
        return result_json_path, preview_png_path

    def _get_crop_bounds(self, wb: WaterBody, obs: SatelliteObservation) -> Tuple[float, float, float, float]:
        """Resolves crop bounds from observation metadata or water body bounding box with padding."""
        if obs.aoi_bounds:
            try:
                b = json.loads(obs.aoi_bounds) if isinstance(obs.aoi_bounds, str) else obs.aoi_bounds
                if len(b) == 4:
                    return tuple(float(x) for x in b)
            except Exception:
                pass

        # Fallback to water body bounds with 15% padding
        min_lon = wb.min_lon or 0.0
        min_lat = wb.min_lat or 0.0
        max_lon = wb.max_lon or (min_lon + 0.01)
        max_lat = wb.max_lat or (min_lat + 0.01)
        pad_x = (max_lon - min_lon) * 0.15
        pad_y = (max_lat - min_lat) * 0.15
        return (min_lon - pad_x, min_lat - pad_y, max_lon + pad_x, max_lat + pad_y)

    def check_band_availability(self, water_body_id: str, observation_id: str, indicator: str) -> BandAvailabilityInfo:
        wb = self._get_water_body_or_404(water_body_id)
        obs = self._get_observation_or_404(water_body_id, observation_id)

        ind_id = indicator.lower().strip()
        ind_cls = INDICATOR_REGISTRY.get(ind_id)
        if not ind_cls:
            raise SpectralServiceError(f"Unknown indicator '{indicator}'.", code="INVALID_INDICATOR")

        required = list(ind_cls.REQUIRED_BANDS)
        available = self.band_loader.check_available_bands(wb, obs)
        missing = [b for b in required if b not in available]

        is_ready = len(missing) == 0
        if is_ready:
            msg = f"All required spectral bands ({', '.join(required)}) are available."
        else:
            msg = (
                f"Required spectral data is not available for this observation. "
                f"Required: {', '.join(required)}. Available: {', '.join(available) or 'None'}. "
                f"Missing: {', '.join(missing)}."
            )

        return BandAvailabilityInfo(
            observation_id=obs.id,
            external_scene_id=obs.external_scene_id,
            indicator=ind_id,
            required_bands=required,
            available_bands=available,
            missing_bands=missing,
            is_ready=is_ready,
            message=msg,
        )

    async def analyze_indicator(
        self,
        water_body_id: str,
        observation_id: str,
        indicator: str,
        force_recompute: bool = False,
    ) -> SpectralAnalysisResult:
        """
        Executes on-demand spectral calculation for the requested indicator.
        Checks cache -> loads AOI bands -> applies geometry & cloud masks ->
        computes statistics & classification -> renders preview -> caches result.
        """
        wb = self._get_water_body_or_404(water_body_id)
        obs = self._get_observation_or_404(water_body_id, observation_id)
        ind_id = indicator.lower().strip()

        ind_cls = INDICATOR_REGISTRY.get(ind_id)
        if not ind_cls:
            raise SpectralServiceError(f"Unknown indicator '{indicator}'.", code="INVALID_INDICATOR")

        result_json_path, preview_png_path = self._get_spectral_cache_paths(wb.id, obs.external_scene_id, ind_id)

        # 1. Check cache (lazy on-demand retrieval)
        if result_json_path.exists() and not force_recompute:
            try:
                cached_data = json.loads(result_json_path.read_text(encoding="utf-8"))
                result = SpectralAnalysisResult(**cached_data)
                result.is_cached = True
                logger.info("Serving cached spectral result for %s - %s", obs.external_scene_id, ind_id)
                return result
            except Exception as exc:
                logger.warning("Corrupt spectral cache file %s: %s. Recomputing.", result_json_path, exc)

        crop_bounds = self._get_crop_bounds(wb, obs)

        # 2. Handle Surface Spectral Anomaly specifically
        if ind_id == SpectralAnomalyIndicator.ID:
            return await self._analyze_anomaly(wb, obs, crop_bounds, result_json_path, preview_png_path)

        # 3. Check Band Availability
        required_bands = list(ind_cls.REQUIRED_BANDS)
        loaded_bands: Dict[str, np.ndarray] = {}

        for b in required_bands:
            arr = await self.band_loader.load_band(wb, obs, b, crop_bounds)
            if arr is not None:
                loaded_bands[b] = arr

        # Check SCL cloud mask layer
        scl_arr = await self.band_loader.load_band(wb, obs, "SCL", crop_bounds)

        missing = [b for b in required_bands if b not in loaded_bands]
        if missing:
            avail = list(loaded_bands.keys())
            raise SpectralServiceError(
                f"Required spectral data is not available for this observation. "
                f"Required: {', '.join(required_bands)}. Available: {', '.join(avail) or 'None'}.",
                code="MISSING_SPECTRAL_BANDS",
                details={
                    "observation_id": obs.id,
                    "external_scene_id": obs.external_scene_id,
                    "indicator": ind_id,
                    "required_bands": required_bands,
                    "available_bands": avail,
                    "missing_bands": missing,
                },
            )

        # 4. Geometry & Cloud Masking
        # Base shape is defined by first loaded band
        first_band_arr = next(iter(loaded_bands.values()))
        base_shape = first_band_arr.shape

        # Geometry vector mask (True = inside water body polygon)
        geometry_geojson = obs.aoi_geojson or wb.geometry_geojson
        water_mask, is_exact_polygon = WaterBodyAOIProcessor.create_water_mask(
            geometry_geojson=geometry_geojson,
            crop_bounds=crop_bounds,
            shape=base_shape,
        )

        # Cloud & shadow mask (True = clear sky)
        clear_mask, cloud_pct, is_scl_avail = SCLCloudMasker.create_mask(scl_arr, base_shape)

        # Valid participating water pixels
        valid_water_mask = water_mask & clear_mask
        total_water_pixels = int(np.sum(water_mask))

        # 5. Indicator Calculation
        if ind_id == TurbidityIndicator.ID:
            index_arr = TurbidityIndicator.calculate(b04=loaded_bands["B04"], b03=loaded_bands["B03"])
        elif ind_id == ChlorophyllIndicator.ID:
            index_arr = ChlorophyllIndicator.calculate(b04=loaded_bands["B04"], b05=loaded_bands["B05"])
        elif ind_id == AlgalActivityIndicator.ID:
            index_arr = AlgalActivityIndicator.calculate(
                b04=loaded_bands["B04"], b05=loaded_bands["B05"], b08=loaded_bands["B08"]
            )
        else:
            raise SpectralServiceError(f"Unsupported indicator calculation: {ind_id}")

        # 6. Statistics Calculation
        stats = SpectralStatistics.calculate(
            data=index_arr,
            valid_mask=valid_water_mask,
            total_water_pixels=total_water_pixels,
        )

        # Quality and classification
        val = stats["value"]
        if val is not None:
            classification, classification_desc = ind_cls.classify(val)
            quality = stats["quality"]
            quality_reason = stats["quality_reason"]
            if not is_scl_avail and quality == QualityLevel.GOOD.value:
                quality = QualityLevel.LIMITED.value
                quality_reason = "Cloud mask unavailable. Result quality: LIMITED."
        else:
            classification = "INSUFFICIENT DATA"
            classification_desc = stats.get("quality_reason") or "Insufficient valid water pixels."
            quality = QualityLevel.INSUFFICIENT.value
            quality_reason = stats.get("quality_reason")

        # 7. Render Preview
        preview_url = f"/api/v1/water-bodies/{wb.id}/spectral/results/{obs.id}_{ind_id}/image"
        try:
            # Check if background RGB can be loaded for contextual preview
            bg_rgb = await self.band_loader.load_band(wb, obs, "B04", crop_bounds)
            ind_cls.render_preview(
                index_arr=index_arr,
                water_mask=water_mask,
                valid_mask=valid_water_mask,
                output_path=str(preview_png_path),
            )
        except Exception as preview_exc:
            logger.warning("Failed to render preview image for %s: %s", ind_id, preview_exc)

        # 8. Construct Result Object
        result = SpectralAnalysisResult(
            id=f"{obs.id}_{ind_id}",
            water_body_id=wb.id,
            water_body_name=wb.name,
            observation_id=obs.id,
            external_scene_id=obs.external_scene_id,
            sensing_date=obs.sensing_date,
            sensing_date_str=obs.sensing_date.strftime("%Y-%m-%d"),
            indicator=ind_id,
            indicator_label=ind_cls.LABEL,
            index_name=ind_cls.INDEX_NAME,
            value=val,
            mean=stats["mean"],
            median=stats["median"],
            std=stats["std"],
            minimum=stats["minimum"],
            maximum=stats["maximum"],
            valid_pixel_count=stats["valid_pixel_count"],
            total_water_pixels=stats["total_water_pixels"],
            valid_pixel_percent=stats["valid_pixel_percent"],
            cloud_pixel_percent=cloud_pct,
            quality=quality,
            quality_reason=quality_reason,
            classification=classification,
            classification_desc=classification_desc,
            preview_url=preview_url,
            formula=ind_cls.FORMULA,
            disclaimer=ind_cls.DISCLAIMER,
            required_bands=required_bands,
            available_bands=list(loaded_bands.keys()),
            missing_bands=[],
            is_cached=False,
        )

        # Cache result JSON
        result_json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    async def _analyze_anomaly(
        self,
        wb: WaterBody,
        obs: SatelliteObservation,
        crop_bounds: Tuple[float, float, float, float],
        result_json_path: Path,
        preview_png_path: Path,
    ) -> SpectralAnalysisResult:
        """
        Calculates Surface Spectral Anomaly by comparing the selected observation
        against historical observations of the SAME water body.
        """
        # Current observation value (uses NDTI as baseline reflectance index)
        current_res = await self.analyze_indicator(wb.id, obs.id, TurbidityIndicator.ID)
        current_val = current_res.value

        # Load all observations for this water body ordered chronologically
        all_obs = self.obs_repo.list_for_water_body(wb.id)
        historical_values: List[float] = []

        for other_obs in all_obs:
            if other_obs.id == obs.id:
                continue
            # Try to get cached or quick NDTI for other observations
            try:
                other_res = await self.analyze_indicator(wb.id, other_obs.id, TurbidityIndicator.ID)
                if other_res.value is not None and other_res.quality != QualityLevel.INSUFFICIENT.value:
                    historical_values.append(other_res.value)
            except Exception as hist_exc:
                logger.debug("Could not compute historical value for obs %s: %s", other_obs.id, hist_exc)

        if current_val is None:
            z_score = None
            hist_mean = None
            hist_std = None
            quality = QualityLevel.INSUFFICIENT.value
            classification = "INSUFFICIENT DATA"
            desc = "Current observation lacks sufficient clear water pixels to calculate spectral anomaly."
        else:
            z_score, hist_mean, hist_std, quality, classification, desc = SpectralAnomalyIndicator.calculate_anomaly(
                current_val=current_val, historical_values=historical_values
            )

        preview_url = f"/api/v1/water-bodies/{wb.id}/spectral/results/{obs.id}_anomaly/image"
        # Mirror turbidity preview for visualization if present
        ndti_prev = self.data_dir / "water_bodies" / wb.id / "observations" / obs.external_scene_id / "spectral" / "ndti_preview.png"
        if ndti_prev.exists() and not preview_png_path.exists():
            try:
                preview_png_path.write_bytes(ndti_prev.read_bytes())
            except Exception:
                pass

        result = SpectralAnalysisResult(
            id=f"{obs.id}_anomaly",
            water_body_id=wb.id,
            water_body_name=wb.name,
            observation_id=obs.id,
            external_scene_id=obs.external_scene_id,
            sensing_date=obs.sensing_date,
            sensing_date_str=obs.sensing_date.strftime("%Y-%m-%d"),
            indicator=SpectralAnomalyIndicator.ID,
            indicator_label=SpectralAnomalyIndicator.LABEL,
            index_name=SpectralAnomalyIndicator.INDEX_NAME,
            value=z_score,
            mean=hist_mean,
            median=current_val,
            std=hist_std,
            minimum=round(min(historical_values), 4) if historical_values else None,
            maximum=round(max(historical_values), 4) if historical_values else None,
            valid_pixel_count=len(historical_values),
            total_water_pixels=len(all_obs),
            valid_pixel_percent=round((len(historical_values) / max(len(all_obs), 1)) * 100.0, 1),
            cloud_pixel_percent=current_res.cloud_pixel_percent,
            quality=quality,
            quality_reason=desc if quality != QualityLevel.GOOD.value else None,
            classification=classification,
            classification_desc=desc,
            baseline_mean=hist_mean,
            baseline_std=hist_std,
            anomaly_score=z_score,
            preview_url=preview_url,
            formula=SpectralAnomalyIndicator.FORMULA,
            disclaimer=SpectralAnomalyIndicator.DISCLAIMER,
            required_bands=SpectralAnomalyIndicator.REQUIRED_BANDS,
            available_bands=current_res.available_bands,
            missing_bands=[],
            is_cached=False,
        )

        result_json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    def get_preview_image_path(self, water_body_id: str, result_id: str) -> Path:
        """Resolves local PNG preview path for a spectral result."""
        # result_id format: {obs_id}_{indicator}
        parts = result_id.rsplit("_", 1)
        if len(parts) != 2:
            raise SpectralServiceError(f"Invalid spectral result ID '{result_id}'.", code="INVALID_RESULT_ID")

        obs_id, indicator = parts
        obs = self._get_observation_or_404(water_body_id, obs_id)
        _, preview_path = self._get_spectral_cache_paths(water_body_id, obs.external_scene_id, indicator)

        if not preview_path.exists():
            raise SpectralServiceError(
                f"Preview image not found for result '{result_id}'.", code="PREVIEW_NOT_FOUND"
            )
        return preview_path

    async def run_time_series_analysis(
        self,
        water_body_id: str,
        observation_ids: List[str],
        indicator: str,
        force_recompute: bool = False,
    ) -> TimeSeriesSpectralResponse:
        wb = self._get_water_body_or_404(water_body_id)
        results: List[SpectralAnalysisResult] = []

        for obs_id in observation_ids:
            try:
                res = await self.analyze_indicator(
                    water_body_id=wb.id,
                    observation_id=obs_id,
                    indicator=indicator,
                    force_recompute=force_recompute,
                )
                results.append(res)
            except Exception as exc:
                logger.warning("Failed time-series spectral calculation for obs %s: %s", obs_id, exc)

        # Sort chronologically
        results.sort(key=lambda r: r.sensing_date)

        return TimeSeriesSpectralResponse(
            water_body_id=wb.id,
            water_body_name=wb.name,
            indicator=indicator,
            total_requested=len(observation_ids),
            total_analyzed=len(results),
            results=results,
        )

    def get_multi_indicator_summary(self, water_body_id: str, observation_id: str) -> MultiIndicatorSummary:
        wb = self._get_water_body_or_404(water_body_id)
        obs = self._get_observation_or_404(water_body_id, observation_id)

        indicators_summary: Dict[str, Optional[SpectralAnalysisResult]] = {}
        for ind_id in [TurbidityIndicator.ID, ChlorophyllIndicator.ID, AlgalActivityIndicator.ID, SpectralAnomalyIndicator.ID]:
            result_json_path, _ = self._get_spectral_cache_paths(wb.id, obs.external_scene_id, ind_id)
            if result_json_path.exists():
                try:
                    data = json.loads(result_json_path.read_text(encoding="utf-8"))
                    res = SpectralAnalysisResult(**data)
                    res.is_cached = True
                    indicators_summary[ind_id] = res
                except Exception:
                    indicators_summary[ind_id] = None
            else:
                indicators_summary[ind_id] = None

        return MultiIndicatorSummary(
            water_body_id=wb.id,
            observation_id=obs.id,
            sensing_date_str=obs.sensing_date.strftime("%Y-%m-%d"),
            indicators=indicators_summary,
        )
