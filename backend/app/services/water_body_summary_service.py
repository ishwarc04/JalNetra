from dataclasses import dataclass
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.water_body import WaterBody
from app.db.models.satellite_observation import SatelliteObservation
from app.db.repositories.water_body_repository import WaterBodyRepository
from app.db.repositories.satellite_observation_repository import SatelliteObservationRepository
from app.services.spectral.service import SpectralAnalysisService
from app.services.water_quality_summary_service import WaterQualitySummaryService, WaterQualitySummary
from app.services.water_body_service import WaterBodyNotFoundError
from app.services.satellite.image_resolver import ObservationImageResolver


@dataclass
class WaterBodyTelegramSummary:
    id: str
    name: str
    location: str
    surface_area_sq_km: Optional[float]
    surface_area_text: str
    water_volume: str
    water_volume_is_estimate: bool
    water_volume_note: Optional[str]
    latest_observation_id: Optional[str]
    latest_observation_date: str
    cloud_cover: str
    apparent_water_extent: str
    observation_count: int
    monitoring_start: Optional[str]
    monitoring_end: Optional[str]
    observation_frequency: str
    water_quality_label: str
    water_quality_simple_text: str
    quality_is_remote_sensing_proxy: bool
    has_stored_visual_image: bool
    latest_image_path: Optional[str] = None  # Internal backend filesystem path only
    image_url: Optional[str] = None
    google_maps_url: Optional[str] = None


class WaterBodySummaryService:
    """
    Shared service for retrieving consolidated water body summaries, observation histories,
    and latest visual observation assets for Telegram, REST API, and AI assistant.
    """

    def __init__(self, db: Session, data_dir: Optional[Path] = None):
        self.db = db
        self.data_dir = data_dir or settings.resolved_data_dir
        self.wb_repo = WaterBodyRepository(db)
        self.obs_repo = SatelliteObservationRepository(db)

    def list_water_bodies(self) -> List[WaterBody]:
        """Returns all registered active water bodies."""
        items, _ = self.wb_repo.list_water_bodies(is_active=True, limit=500)
        # Sort alphabetically by name
        items.sort(key=lambda w: (w.name or "").lower())
        return items

    def find_water_bodies(self, query: str) -> List[WaterBody]:
        """
        Finds water bodies matching a query.
        Prioritizes exact match; falls back to case-insensitive substring matching.
        """
        q = (query or "").strip().lower()
        if not q:
            return []

        all_wbs = self.list_water_bodies()

        # 1. Exact match priority
        for wb in all_wbs:
            wb_name = (wb.name or "").strip().lower()
            norm_name = (wb.normalized_name or "").strip().lower()
            if wb_name == q or norm_name == q:
                return [wb]

        # 2. Substring matching
        matches = []
        for wb in all_wbs:
            wb_name = (wb.name or "").strip().lower()
            norm_name = (wb.normalized_name or "").strip().lower()
            if q in wb_name or (norm_name and q in norm_name):
                matches.append(wb)

        return matches

    @staticmethod
    def get_water_volume_summary(wb: WaterBody) -> Tuple[str, bool, Optional[str]]:
        """
        Derives water volume summary:
        Returns (volume_str, is_estimate, volume_note).
        Priority:
        1. Stored measured volume if available in DB.
        2. Deterministic demo estimate from surface area.
        3. 'Not available' if surface area is missing.
        """
        if wb.area_sq_km and wb.area_sq_km > 0:
            area = wb.area_sq_km
            # Depth proxy depending on scale:
            # < 1 km² -> ~2.5m, 1-50 km² -> ~6m, > 50 km² -> ~12m
            if area < 1.0:
                depth_m = 2.5
            elif area <= 50.0:
                depth_m = 6.0
            else:
                depth_m = 12.0

            vol_m3 = area * 1_000_000.0 * depth_m
            if vol_m3 >= 1_000_000_000:
                vol_str = f"~{vol_m3 / 1_000_000_000.0:.2f} billion m³"
            else:
                vol_str = f"~{vol_m3 / 1_000_000.0:.1f} million m³"

            return (
                vol_str,
                True,
                "Demo estimate — actual volume requires measured depth/bathymetry data.",
            )

        return ("Not available", False, None)

    @staticmethod
    def get_monitoring_frequency(observations: List[SatelliteObservation]) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Computes observation frequency statistics across observation dates.
        Returns (frequency_text, start_date_str, end_date_str).
        """
        if not observations:
            return ("No observations available", None, None)

        if len(observations) == 1:
            d_str = observations[0].sensing_date.strftime("%d %b %Y")
            return ("1 observation available", d_str, d_str)

        start_dt = observations[0].sensing_date
        end_dt = observations[-1].sensing_date
        start_str = start_dt.strftime("%d %b %Y")
        end_str = end_dt.strftime("%d %b %Y")

        gaps = [(observations[i].sensing_date - observations[i - 1].sensing_date).days for i in range(1, len(observations))]
        if not gaps:
            return (f"{len(observations)} observations available", start_str, end_str)

        avg_gap = sum(gaps) / len(gaps)
        if len(gaps) > 1:
            variance = sum((g - avg_gap) ** 2 for g in gaps) / (len(gaps) - 1)
            std_dev = math.sqrt(variance)
        else:
            std_dev = 0.0

        if std_dev <= 7.0 or (avg_gap > 0 and std_dev / avg_gap < 0.4):
            freq_text = f"Approximately every {int(round(avg_gap))} days"
        else:
            freq_text = f"Irregular — {len(observations)} observations available during monitoring period"

        return (freq_text, start_str, end_str)

    def get_latest_visual_observation(
        self, water_body_id: str
    ) -> Optional[Tuple[SatelliteObservation, Path]]:
        """
        Finds the newest observation for a water body that has an existing local visual image on disk.
        Returns (observation, absolute_path_to_image) or None.
        """
        return ObservationImageResolver.get_latest_visual_observation(
            water_body_id, self.db, data_dir=self.data_dir
        )

    def get_water_body_summary(self, water_body_id: str) -> WaterBodyTelegramSummary:
        """Assembles a full summary for a water body from the database and storage."""
        wb = self.wb_repo.get_by_id(water_body_id)
        if not wb:
            raise WaterBodyNotFoundError(f"Water body with ID '{water_body_id}' not found.")

        # 1. Location
        loc_parts = [p for p in [wb.city, wb.district, wb.state_province, wb.country] if p]
        if loc_parts:
            location_str = ", ".join(loc_parts)
        elif wb.centroid_lat is not None and wb.centroid_lon is not None:
            location_str = f"{wb.centroid_lat:.2f}°N, {wb.centroid_lon:.2f}°E"
        else:
            location_str = "Location unspecified"

        # Google Maps URL
        google_maps_url = None
        if wb.centroid_lat is not None and wb.centroid_lon is not None:
            google_maps_url = f"https://www.google.com/maps/search/?api=1&query={wb.centroid_lat},{wb.centroid_lon}"

        # 2. Surface area
        if wb.area_sq_km and wb.area_sq_km > 0:
            area_text = f"~{wb.area_sq_km:,.3g} km²"
        else:
            area_text = "Not available"

        # 3. Water volume
        vol_str, vol_is_est, vol_note = self.get_water_volume_summary(wb)

        # 4. Observations & Timeline
        obs_list = self.obs_repo.list_for_water_body(wb.id)
        obs_list.sort(key=lambda o: o.sensing_date)
        obs_count = len(obs_list)
        freq_text, start_date, end_date = self.get_monitoring_frequency(obs_list)

        # 5. Latest visual observation on disk
        latest_visual_result = self.get_latest_visual_observation(wb.id)
        latest_obs = latest_visual_result[0] if latest_visual_result else (obs_list[-1] if obs_list else None)
        image_path = str(latest_visual_result[1]) if latest_visual_result else None
        has_stored_image = latest_visual_result is not None

        if latest_obs:
            latest_obs_id = latest_obs.id
            latest_date_str = latest_obs.sensing_date.strftime("%d %b %Y")
            cc = getattr(latest_obs, "cloud_cover_percent", None)
            if cc is None:
                cc = getattr(latest_obs, "cloud_cover_percentage", None)
            cloud_cover_str = f"{cc:.1f}%" if cc is not None else "Not available"

            extent = getattr(latest_obs, "derived_water_area_sq_km", None)
            if extent is None:
                extent = getattr(latest_obs, "apparent_water_extent_sq_km", None)
            apparent_extent_str = f"~{extent:,.3g} km²" if extent is not None else "Not measured"
            image_url = f"/api/v1/water-bodies/{wb.id}/observations/{latest_obs.id}/image" if has_stored_image else None
        else:
            latest_obs_id = None
            latest_date_str = "No observations"
            cloud_cover_str = "Not available"
            apparent_extent_str = "Not available"
            image_url = None

        # 6. Water quality from spectral indicators
        indicators_dict = {}
        if latest_obs:
            try:
                spectral_svc = SpectralAnalysisService(self.db, data_dir=self.data_dir)
                summary_data = spectral_svc.get_multi_indicator_summary(wb.id, latest_obs.id)
                indicators_dict = summary_data.indicators
            except Exception:
                indicators_dict = {}

        has_clear = (latest_obs is not None and getattr(latest_obs, "cloud_cover_percent", 100) < 25.0)
        wq_summary = WaterQualitySummaryService.summarize_indicators(indicators_dict, has_clear_observation=has_clear)

        return WaterBodyTelegramSummary(
            id=wb.id,
            name=wb.name,
            location=location_str,
            surface_area_sq_km=wb.area_sq_km,
            surface_area_text=area_text,
            water_volume=vol_str,
            water_volume_is_estimate=vol_is_est,
            water_volume_note=vol_note,
            latest_observation_id=latest_obs_id,
            latest_observation_date=latest_date_str,
            cloud_cover=cloud_cover_str,
            apparent_water_extent=apparent_extent_str,
            observation_count=obs_count,
            monitoring_start=start_date,
            monitoring_end=end_date,
            observation_frequency=freq_text,
            water_quality_label=wq_summary.label,
            water_quality_simple_text=wq_summary.simple_view,
            quality_is_remote_sensing_proxy=wq_summary.is_remote_sensing_proxy,
            has_stored_visual_image=has_stored_image,
            latest_image_path=image_path,
            image_url=image_url,
            google_maps_url=google_maps_url,
        )

    @staticmethod
    def format_telegram_summary_message(s: WaterBodyTelegramSummary) -> str:
        """Formats the water-body summary into clean, readable Markdown text."""
        lines = [
            f"🌊 {s.name.upper()}",
            "",
            "📍 Location",
            s.location,
        ]

        if s.google_maps_url:
            lines.extend([
                "",
                "🗺 Location",
                f"[Open in Google Maps]({s.google_maps_url})",
            ])

        lines.extend([
            "",
            "📐 Surface Area",
            s.surface_area_text,
            "",
            "💧 Estimated Water Volume",
            s.water_volume,
        ])

        if s.water_volume_note:
            lines.append(s.water_volume_note)

        lines.extend([
            "",
            "🛰 Latest Observation",
            s.latest_observation_date,
            "",
            "☁ Cloud Cover",
            s.cloud_cover,
            "",
            "🌊 Apparent Water Extent",
            s.apparent_water_extent,
            "",
            "🔄 Change Frequency",
            f"Observed across {s.observation_count} available observation{'s' if s.observation_count != 1 else ''}",
        ])

        if s.monitoring_start and s.monitoring_end:
            lines.append(f"Monitoring period: {s.monitoring_start} → {s.monitoring_end}")
        lines.append(f"Frequency: {s.observation_frequency}")

        lines.extend([
            "",
            "💧 Water Quality",
            s.water_quality_label,
            "",
            "Simple view:",
            f'"{s.water_quality_simple_text}"',
        ])

        if not s.has_stored_visual_image:
            if s.observation_count > 0:
                lines.extend([
                    "",
                    "🛰 Latest Visual",
                    "Observation exists, image unavailable.",
                    "",
                    f"Available observations: {s.observation_count}",
                    "The latest observation does not currently have a readable visual file.",
                ])
            else:
                lines.extend([
                    "",
                    "🛰 Latest Visual",
                    "No visual observations have been fetched yet.",
                    "Use the JalNetra application to fetch visual observations first.",
                ])

        return "\n".join(lines)
