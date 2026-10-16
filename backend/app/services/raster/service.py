"""
Raster Orchestrator Service for JalNetra.
Coordinates metadata queries, cache lookup, on-demand RGB rendering, and bounds computation.
"""
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import json
import hashlib
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.satellite_scene import SatelliteScene
from app.db.models.satellite_asset import SatelliteAsset
from app.services.raster.models import (
    SceneRasterMetadataResponse,
    AssetMetadata,
    RGBVisualizationResponse,
    GeoBounds,
)
from app.services.raster.reader import RasterReader
from app.services.raster.renderer import RGBRenderer


class RasterService:
    """Service providing high-level raster metadata and RGB rendering for satellite scenes."""

    def __init__(self, data_dir: Optional[Path] = None):
        self._custom_data_dir = data_dir

    @property
    def data_dir(self) -> Path:
        return self._custom_data_dir or settings.resolved_data_dir

    @property
    def processed_dir(self) -> Path:
        d = self.data_dir / "processed" / "map"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_scene_metadata(self, db: Session, scene_id: str) -> SceneRasterMetadataResponse:
        """
        Inspects scene assets in SQLite and on disk.
        Returns comprehensive metadata including CRS, dimensions, resolution, and geographic bounds.
        """
        scene = db.query(SatelliteScene).filter(SatelliteScene.id == scene_id).first()
        if not scene:
            # Also try matching by external_scene_id for convenience
            scene = db.query(SatelliteScene).filter(SatelliteScene.external_scene_id == scene_id).first()
        if not scene:
            raise ValueError(f"Satellite scene not found: {scene_id}")

        assets = db.query(SatelliteAsset).filter(SatelliteAsset.scene_id == scene.id).all()
        
        asset_meta_list: List[AssetMetadata] = []
        primary_geo_bounds: Optional[GeoBounds] = None
        primary_crs: Optional[str] = None
        primary_native_bounds: Optional[dict] = None

        downloaded_band_keys = set()

        for asset in assets:
            is_downloaded = asset.status == "downloaded" and asset.local_path is not None
            file_path = (self.data_dir / asset.local_path) if asset.local_path else None
            exists = file_path.exists() if file_path else False

            meta = AssetMetadata(
                asset_key=asset.asset_key,
                asset_type=asset.asset_type,
                file_size_bytes=asset.file_size_bytes,
                is_downloaded=is_downloaded and exists,
            )

            # If it's a GeoTIFF and exists locally, inspect raster headers
            if exists and file_path and file_path.suffix.lower() in [".tif", ".tiff"]:
                downloaded_band_keys.add(asset.asset_key)
                try:
                    insp = RasterReader.inspect_file(file_path)
                    meta.crs = insp.get("crs")
                    meta.width = insp.get("width")
                    meta.height = insp.get("height")
                    meta.resolution_meters = insp.get("resolution_meters")
                    meta.nodata = insp.get("nodata")

                    if not primary_geo_bounds and insp.get("geographic_bounds"):
                        gb = insp["geographic_bounds"]
                        primary_geo_bounds = GeoBounds(
                            west=gb["west"],
                            south=gb["south"],
                            east=gb["east"],
                            north=gb["north"],
                        )
                    if not primary_crs:
                        primary_crs = insp.get("crs")
                    if not primary_native_bounds:
                        primary_native_bounds = insp.get("native_bounds")
                except Exception:
                    pass

            asset_meta_list.append(meta)

        # Fallback to scene's stored bbox if raster inspection did not set bounds
        if not primary_geo_bounds and scene.bbox_min_lat is not None:
            primary_geo_bounds = GeoBounds(
                west=scene.bbox_min_lon or 0.0,
                south=scene.bbox_min_lat or 0.0,
                east=scene.bbox_max_lon or 0.0,
                north=scene.bbox_max_lat or 0.0,
            )

        # Check if RGB bands (B04, B03, B02) are present
        rgb_available = {"B04", "B03", "B02"}.issubset(downloaded_band_keys)
        
        # Check if cached visualization exists
        cache_png = self.processed_dir / scene.id / "rgb.png"
        rgb_cached = cache_png.exists()

        return SceneRasterMetadataResponse(
            scene_id=scene.id,
            external_scene_id=scene.external_scene_id,
            provider=scene.provider,
            collection=scene.collection,
            sensing_start=scene.sensing_start.isoformat(),
            cloud_cover_percent=scene.cloud_cover_percent,
            crs=primary_crs,
            geographic_bounds=primary_geo_bounds,
            native_bounds=primary_native_bounds,
            available_assets=asset_meta_list,
            rgb_available=rgb_available,
            rgb_cached=rgb_cached,
            image_url=f"/api/v1/map/scenes/{scene.id}/rgb/image" if (rgb_available or rgb_cached) else None,
        )

    @staticmethod
    def compute_cache_key(
        scene_id: str,
        water_body_id: Optional[str] = None,
        crop_bbox: Optional[Tuple[float, float, float, float]] = None,
        padding_percent: Optional[float] = None,
    ) -> str:
        """
        Computes a deterministic hash and prefix for raster visualization caching,
        preventing cross-water-body, cross-AOI, or cross-scene cache collisions.
        """
        parts = [
            f"scene:{scene_id}",
            f"wb:{water_body_id or 'none'}",
            f"bbox:{','.join(str(round(c, 5)) for c in crop_bbox) if crop_bbox else 'none'}",
            f"pad:{round(padding_percent, 2) if padding_percent is not None else 'default'}",
        ]
        raw_str = "|".join(parts)
        digest = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:12]
        if crop_bbox:
            w, s, e, n = crop_bbox
            prefix = f"aoi_{round(w, 4)}_{round(s, 4)}_{round(e, 4)}_{round(n, 4)}"
        elif water_body_id:
            prefix = f"wb_{water_body_id}"
        else:
            prefix = "full"
        return f"{prefix}_{digest}"

    def get_or_render_rgb(
        self,
        db: Session,
        scene_id: str,
        water_body_id: Optional[str] = None,
        crop_bbox: Optional[Tuple[float, float, float, float]] = None,
        padding_percent: Optional[float] = None,
        force_regenerate: bool = False,
    ) -> RGBVisualizationResponse:
        """
        Retrieves cached RGB visualization or renders it on demand from B04, B03, and B02.
        If crop_bbox or water_body_id is specified, validates spatial intersection,
        crops and focuses the RGB raster, and saves result to an isolated cache key.
        """
        scene = db.query(SatelliteScene).filter(SatelliteScene.id == scene_id).first()
        if not scene:
            scene = db.query(SatelliteScene).filter(SatelliteScene.external_scene_id == scene_id).first()
        if not scene:
            raise ValueError(f"Satellite scene not found: {scene_id}")

        scene_processed_dir = self.processed_dir / scene.id
        scene_processed_dir.mkdir(parents=True, exist_ok=True)

        # Spatial intersection validation and crop bounds computation
        crop_bounds = None
        is_focused = False

        if crop_bbox:
            # Validate crop_bbox intersects scene if scene bounds are known
            if scene.bbox_min_lon is not None:
                cw, cs, ce, cn = crop_bbox
                no_overlap = (
                    ce < scene.bbox_min_lon or
                    cw > scene.bbox_max_lon or
                    cn < scene.bbox_min_lat or
                    cs > scene.bbox_max_lat
                )
                if no_overlap:
                    raise ValueError("Requested crop bounding box does not intersect satellite scene extent")
            crop_bounds = crop_bbox
            is_focused = True
        elif water_body_id:
            from app.db.models.water_body import WaterBody
            wb = db.query(WaterBody).filter(WaterBody.id == water_body_id).first()
            if not wb:
                raise ValueError(f"Water body with ID '{water_body_id}' not found")

            # Extract WB bounds
            wb_w, wb_s, wb_e, wb_n = wb.min_lon, wb.min_lat, wb.max_lon, wb.max_lat
            if wb_w is None and wb.geometry_geojson:
                try:
                    wb_geom = json.loads(wb.geometry_geojson)
                    from shapely.geometry import shape
                    wb_w, wb_s, wb_e, wb_n = shape(wb_geom).bounds
                except Exception:
                    pass
            if wb_w is None and wb.centroid_lat is not None and wb.centroid_lon is not None:
                wb_w = wb.centroid_lon - 0.01
                wb_s = wb.centroid_lat - 0.01
                wb_e = wb.centroid_lon + 0.01
                wb_n = wb.centroid_lat + 0.01

            # Validate spatial intersection between scene and water body
            if scene.bbox_min_lon is not None and wb_w is not None:
                no_overlap = (
                    wb_e < scene.bbox_min_lon or
                    wb_w > scene.bbox_max_lon or
                    wb_n < scene.bbox_min_lat or
                    wb_s > scene.bbox_max_lat
                )
                if no_overlap:
                    raise ValueError(
                        f"Satellite scene '{scene.external_scene_id}' does not geographically intersect water body '{wb.name}'"
                    )

            if wb_w is not None:
                pad_val = padding_percent if padding_percent is not None else getattr(settings, "WATER_BODY_MAP_PADDING_PERCENT", 10.0)
                pad_pct = pad_val / 100.0
                span_x = wb_e - wb_w
                span_y = wb_n - wb_s
                pad_x = max(span_x * pad_pct, 0.0001)
                pad_y = max(span_y * pad_pct, 0.0001)
                crop_bounds = (wb_w - pad_x, wb_s - pad_y, wb_e + pad_x, wb_n + pad_y)
                is_focused = True

        cache_key = self.compute_cache_key(scene.id, water_body_id, crop_bbox, padding_percent)
        output_png = scene_processed_dir / f"{cache_key}.png"
        meta_json = scene_processed_dir / f"{cache_key}.json"

        # Determine legacy paths for backwards compatibility
        legacy_png = None
        legacy_meta = None
        if not crop_bbox and not water_body_id:
            legacy_png = scene_processed_dir / "rgb.png"
            legacy_meta = scene_processed_dir / "rgb_meta.json"
        elif water_body_id and not crop_bbox:
            if padding_percent is not None and padding_percent != 10.0:
                p_int = int(round(padding_percent))
                legacy_png = scene_processed_dir / f"wb_{water_body_id}_p{p_int}_rgb.png"
                legacy_meta = scene_processed_dir / f"wb_{water_body_id}_p{p_int}_rgb_meta.json"
            else:
                legacy_png = scene_processed_dir / f"wb_{water_body_id}_rgb.png"
                legacy_meta = scene_processed_dir / f"wb_{water_body_id}_rgb_meta.json"
        elif crop_bbox:
            legacy_png = scene_processed_dir / f"aoi_{crop_bbox[0]}_{crop_bbox[1]}_{crop_bbox[2]}_{crop_bbox[3]}_rgb.png"
            legacy_meta = scene_processed_dir / f"aoi_{crop_bbox[0]}_{crop_bbox[1]}_{crop_bbox[2]}_{crop_bbox[3]}_rgb_meta.json"

        # Check existing cache
        target_meta_file = None
        if not force_regenerate and output_png.exists() and meta_json.exists():
            target_meta_file = meta_json
        elif not force_regenerate and legacy_png and legacy_png.exists() and legacy_meta and legacy_meta.exists():
            target_meta_file = legacy_meta

        sensing_date_str = scene.sensing_start.strftime("%Y-%m-%d") if scene.sensing_start else None

        if target_meta_file:
            try:
                with open(target_meta_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                img_url = f"/api/v1/map/scenes/{scene.id}/rgb/image"
                params = []
                if crop_bbox:
                    params.append(f"bbox={crop_bbox[0]},{crop_bbox[1]},{crop_bbox[2]},{crop_bbox[3]}")
                if water_body_id:
                    params.append(f"water_body_id={water_body_id}")
                if padding_percent is not None and padding_percent != 10.0:
                    params.append(f"padding_percent={padding_percent}")
                if params:
                    img_url += "?" + "&".join(params)

                return RGBVisualizationResponse(
                    scene_id=scene.id,
                    external_scene_id=scene.external_scene_id,
                    water_body_id=water_body_id,
                    is_focused=is_focused,
                    crs="EPSG:4326",
                    source_crs=cached_data.get("source_crs", "EPSG:32643"),
                    resolution_m=cached_data.get("resolution_m", 10.0),
                    bands=cached_data.get("bands", ["B04", "B03", "B02"]),
                    sensing_date=cached_data.get("sensing_date", sensing_date_str),
                    bounds=GeoBounds(**cached_data["bounds"]),
                    width=cached_data["width"],
                    height=cached_data["height"],
                    image_url=img_url,
                    cached=True,
                )
            except Exception:
                pass  # Fall through to re-render if cached meta is corrupted

        # Locate B04, B03, B02 assets
        assets = db.query(SatelliteAsset).filter(SatelliteAsset.scene_id == scene.id).all()
        asset_map = {a.asset_key: a for a in assets}

        missing = [b for b in ["B04", "B03", "B02"] if b not in asset_map or asset_map[b].status != "downloaded"]
        if missing:
            raise FileNotFoundError(
                f"Cannot render RGB visualization: Missing downloaded band(s) {missing}. "
                f"Please acquire these bands first."
            )

        b04_path = self.data_dir / asset_map["B04"].local_path
        b03_path = self.data_dir / asset_map["B03"].local_path
        b02_path = self.data_dir / asset_map["B02"].local_path

        # Render RGB visualization with optional crop
        render_res = RGBRenderer.render_rgb(
            red_path=b04_path,
            green_path=b03_path,
            blue_path=b02_path,
            output_png_path=output_png,
            crop_bounds=crop_bounds,
        )

        # Cache metadata
        meta_to_save = {
            "scene_id": scene.id,
            "external_scene_id": scene.external_scene_id,
            "water_body_id": water_body_id,
            "is_focused": is_focused,
            "bounds": render_res["bounds"].model_dump(),
            "width": render_res["width"],
            "height": render_res["height"],
            "crs": render_res["crs"],
            "source_crs": "EPSG:32643",
            "resolution_m": 10.0,
            "bands": ["B04", "B03", "B02"],
            "sensing_date": sensing_date_str,
        }
        with open(meta_json, "w", encoding="utf-8") as f:
            json.dump(meta_to_save, f, indent=2)

        # Also populate legacy fallback files if applicable
        if legacy_png and legacy_meta:
            try:
                import shutil
                shutil.copyfile(output_png, legacy_png)
                with open(legacy_meta, "w", encoding="utf-8") as f:
                    json.dump(meta_to_save, f, indent=2)
            except Exception:
                pass

        img_url = f"/api/v1/map/scenes/{scene.id}/rgb/image"
        params = []
        if crop_bbox:
            params.append(f"bbox={crop_bbox[0]},{crop_bbox[1]},{crop_bbox[2]},{crop_bbox[3]}")
        if water_body_id:
            params.append(f"water_body_id={water_body_id}")
        if padding_percent is not None and padding_percent != 10.0:
            params.append(f"padding_percent={padding_percent}")
        if params:
            img_url += "?" + "&".join(params)

        return RGBVisualizationResponse(
            scene_id=scene.id,
            external_scene_id=scene.external_scene_id,
            water_body_id=water_body_id,
            is_focused=is_focused,
            crs="EPSG:4326",
            source_crs="EPSG:32643",
            resolution_m=10.0,
            bands=["B04", "B03", "B02"],
            sensing_date=sensing_date_str,
            bounds=render_res["bounds"],
            width=render_res["width"],
            height=render_res["height"],
            image_url=img_url,
            cached=False,
        )

    def get_rgb_image_path(
        self,
        db: Session,
        scene_id: str,
        water_body_id: Optional[str] = None,
        crop_bbox: Optional[Tuple[float, float, float, float]] = None,
        padding_percent: Optional[float] = None,
    ) -> Path:
        """Returns the filesystem path to the rendered RGB PNG image, rendering if needed."""
        scene = db.query(SatelliteScene).filter(SatelliteScene.id == scene_id).first()
        if not scene:
            scene = db.query(SatelliteScene).filter(SatelliteScene.external_scene_id == scene_id).first()
        if not scene:
            raise ValueError(f"Satellite scene not found: {scene_id}")

        cache_key = self.compute_cache_key(scene.id, water_body_id, crop_bbox, padding_percent)
        img_path = self.processed_dir / scene.id / f"{cache_key}.png"

        # Check legacy path if primary does not exist yet
        if not img_path.exists():
            if not crop_bbox and not water_body_id:
                legacy = self.processed_dir / scene.id / "rgb.png"
                if legacy.exists():
                    return legacy
            elif water_body_id and not crop_bbox:
                legacy = self.processed_dir / scene.id / f"wb_{water_body_id}_rgb.png"
                if legacy.exists():
                    return legacy
            elif crop_bbox:
                legacy = self.processed_dir / scene.id / f"aoi_{crop_bbox[0]}_{crop_bbox[1]}_{crop_bbox[2]}_{crop_bbox[3]}_rgb.png"
                if legacy.exists():
                    return legacy

        if not img_path.exists():
            # Trigger generation
            self.get_or_render_rgb(
                db,
                scene.id,
                water_body_id=water_body_id,
                crop_bbox=crop_bbox,
                padding_percent=padding_percent,
            )

        if not img_path.exists():
            # Fallback to legacy if get_or_render_rgb wrote legacy
            if not crop_bbox and not water_body_id:
                legacy = self.processed_dir / scene.id / "rgb.png"
                if legacy.exists():
                    return legacy
            elif water_body_id and not crop_bbox:
                legacy = self.processed_dir / scene.id / f"wb_{water_body_id}_rgb.png"
                if legacy.exists():
                    return legacy
            elif crop_bbox:
                legacy = self.processed_dir / scene.id / f"aoi_{crop_bbox[0]}_{crop_bbox[1]}_{crop_bbox[2]}_{crop_bbox[3]}_rgb.png"
                if legacy.exists():
                    return legacy
            raise FileNotFoundError(f"RGB visualization could not be generated for scene {scene_id}")

        return img_path
