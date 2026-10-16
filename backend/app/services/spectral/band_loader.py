import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
from PIL import Image
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import from_bounds

from app.core.config import settings
from app.db.models.satellite_observation import SatelliteObservation
from app.db.models.water_body import WaterBody
from app.services.satellite.providers.stac import EarthSearchSTACProvider

logger = logging.getLogger("jalnetra.spectral.band_loader")

BAND_TO_STAC_ASSET = {
    "B02": "blue",
    "B03": "green",
    "B04": "red",
    "B05": "rededge1",
    "B06": "rededge2",
    "B07": "rededge3",
    "B08": "nir",
    "B8A": "nir08",
    "B11": "swir16",
    "B12": "swir22",
    "SCL": "scl",
}


class SpectralBandLoader:
    """
    Loads cropped AOI raster bands for spectral indicator processing.
    Operates strictly on the water-body AOI window (<100KB per band),
    never loading or storing full 100km Sentinel-2 scenes.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path(settings.DATA_DIR)
        self.provider = EarthSearchSTACProvider()

    def get_obs_dir(self, wb_id: str, scene_id: str) -> Path:
        return self.data_dir / "water_bodies" / wb_id / "observations" / scene_id

    def get_spectral_dir(self, wb_id: str, scene_id: str) -> Path:
        spectral_dir = self.get_obs_dir(wb_id, scene_id) / "spectral"
        spectral_dir.mkdir(parents=True, exist_ok=True)
        return spectral_dir

    def check_available_bands(self, wb: WaterBody, obs: SatelliteObservation) -> List[str]:
        """
        Returns list of spectral band names readily available locally on disk or derived.
        """
        spectral_dir = self.get_spectral_dir(wb.id, obs.external_scene_id)
        available = []

        # Check local cropped GeoTIFFs
        for band in ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12", "SCL"]:
            tif_path = spectral_dir / f"{band}.tif"
            if tif_path.exists():
                available.append(band)

        # Check visual rgb.jpg fallback (provides B04, B03, B02)
        if obs.local_visual_path:
            full_rgb = self.data_dir / obs.local_visual_path
            if full_rgb.exists():
                for b in ["B04", "B03", "B02"]:
                    if b not in available:
                        available.append(b)

        return available

    async def load_band(
        self,
        wb: WaterBody,
        obs: SatelliteObservation,
        band: str,
        crop_bounds: Tuple[float, float, float, float],
    ) -> Optional[np.ndarray]:
        """
        Loads a single cropped band array for the water-body AOI.
        Tries local cached GeoTIFF -> remote COG windowed read -> RGB extraction fallback.
        """
        band = band.upper().strip()
        spectral_dir = self.get_spectral_dir(wb.id, obs.external_scene_id)
        cached_tif = spectral_dir / f"{band}.tif"

        # 1. Local cached AOI GeoTIFF
        if cached_tif.exists():
            try:
                with rasterio.open(cached_tif) as src:
                    return src.read(1).astype(np.float32)
            except Exception as exc:
                logger.warning("Error reading local band %s: %s", cached_tif, exc)

        # 2. Windowed read from remote COG URL if accessible
        asset_key = BAND_TO_STAC_ASSET.get(band, band.lower())
        remote_url = None

        # Check metadata.json for STAC URLs or query provider
        meta_path = self.get_obs_dir(wb.id, obs.external_scene_id) / "metadata.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                remote_url = meta.get("band_urls", {}).get(band)
            except Exception:
                pass

        if not remote_url:
            # Query STAC provider directly by scene ID first, then fallback to bbox search
            try:
                sc = await self.provider.get_scene(obs.external_scene_id)
                if sc:
                    if band in sc.assets:
                        remote_url = sc.assets[band].remote_url
                    elif asset_key in sc.assets:
                        remote_url = sc.assets[asset_key].remote_url
                    elif band.lower() in sc.assets:
                        remote_url = sc.assets[band.lower()].remote_url
            except Exception as get_exc:
                logger.debug("Direct get_scene failed for %s: %s", obs.external_scene_id, get_exc)

            if not remote_url:
                try:
                    from datetime import timedelta
                    stac_scenes = await self.provider.search_scenes(
                        bbox=crop_bounds,
                        start_date=obs.sensing_date - timedelta(days=1),
                        end_date=obs.sensing_date + timedelta(days=1),
                        limit=10,
                    )
                    for sc in stac_scenes:
                        if sc.external_scene_id == obs.external_scene_id:
                            if band in sc.assets:
                                remote_url = sc.assets[band].remote_url
                            elif asset_key in sc.assets:
                                remote_url = sc.assets[asset_key].remote_url
                            elif band.lower() in sc.assets:
                                remote_url = sc.assets[band.lower()].remote_url
                            break
                except Exception as stac_exc:
                    logger.debug("Could not resolve remote STAC URL for %s: %s", band, stac_exc)

        if remote_url:
            try:
                arr = self._read_windowed_from_url(remote_url, crop_bounds, is_categorical=(band == "SCL"))
                if arr is not None:
                    # Cache cropped AOI band locally
                    self._save_cropped_band_tif(arr, cached_tif, crop_bounds, is_categorical=(band == "SCL"))
                    return arr
            except Exception as read_exc:
                logger.warning("Windowed read failed for %s from %s: %s", band, remote_url, read_exc)

        # 3. Fallback for RGB bands (B04, B03, B02) from local rgb.jpg
        if band in ("B04", "B03", "B02") and obs.local_visual_path:
            full_rgb_path = self.data_dir / obs.local_visual_path
            if full_rgb_path.exists():
                try:
                    with Image.open(full_rgb_path) as im:
                        rgb = np.array(im.convert("RGB"), dtype=np.float32)
                        # Channel index: 0 = Red (B04), 1 = Green (B03), 2 = Blue (B02)
                        ch_idx = 0 if band == "B04" else 1 if band == "B03" else 2
                        band_arr = rgb[:, :, ch_idx]
                        return band_arr
                except Exception as img_exc:
                    logger.warning("Could not read RGB fallback for %s: %s", band, img_exc)

        return None

    def _read_windowed_from_url(
        self,
        url: str,
        crop_bounds: Tuple[float, float, float, float],
        is_categorical: bool = False,
    ) -> Optional[np.ndarray]:
        """Performs a direct windowed read over HTTP from remote Cloud-Optimized GeoTIFF."""
        cw, cs, ce, cn = crop_bounds
        env_kwargs = {
            "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
            "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
        }
        resampling = Resampling.nearest if is_categorical else Resampling.bilinear

        with rasterio.Env(**env_kwargs):
            with rasterio.open(url) as src:
                vrt_kwargs = {"crs": "EPSG:4326", "resampling": resampling}
                with WarpedVRT(src, **vrt_kwargs) as vrt:
                    rw, rs, re, rn = vrt.bounds
                    int_w = max(cw, rw)
                    int_s = max(cs, rs)
                    int_e = min(ce, re)
                    int_n = min(cn, rn)

                    if int_e <= int_w or int_n <= int_s:
                        return None

                    window = from_bounds(int_w, int_s, int_e, int_n, transform=vrt.transform)
                    dtype = np.uint8 if is_categorical else np.float32
                    arr = vrt.read(1, window=window).astype(dtype)
                    return arr

    def _save_cropped_band_tif(
        self,
        arr: np.ndarray,
        dest_path: Path,
        bounds: Tuple[float, float, float, float],
        is_categorical: bool = False,
    ) -> None:
        """Saves small cropped AOI raster as GeoTIFF (<50 KB)."""
        h, w = arr.shape
        min_lon, min_lat, max_lon, max_lat = bounds
        transform = rasterio.transform.from_bounds(min_lon, min_lat, max_lon, max_lat, w, h)
        dtype = "uint8" if is_categorical else "float32"

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            dest_path,
            "w",
            driver="GTiff",
            height=h,
            width=w,
            count=1,
            dtype=dtype,
            crs="EPSG:4326",
            transform=transform,
            compress="deflate",
        ) as dst:
            dst.write(arr.astype(dtype), 1)
