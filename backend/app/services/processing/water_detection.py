"""
Deterministic Spectral Water Detection Pipeline.
Aligns Sentinel-2 B03 (Green) and B08 (NIR) to a common reference grid,
applies the SCL valid cloud mask, evaluates spectral contrast (Green - NIR)/(Green + NIR) > threshold,
and generates a georeferenced binary water mask:
  0 = non-water / invalid
  1 = detected water
"""
from pathlib import Path
from typing import Dict, Any, Optional
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT


# Centrally configurable default spectral water detection threshold
# Standard normalized green-to-NIR contrast: positive values represent water surface absorption/reflection
DEFAULT_WATER_THRESHOLD: float = 0.0


class WaterDetector:
    """Performs deterministic spectral water segmentation from aligned Sentinel-2 bands."""

    @staticmethod
    def detect_water(
        green_path: Path,
        nir_path: Path,
        cloud_mask_path: Path,
        output_water_mask_path: Path,
        threshold: float = DEFAULT_WATER_THRESHOLD,
    ) -> Dict[str, Any]:
        """
        Reads B03 (Green), B08 (NIR), and the cloud/valid mask GeoTIFF.
        Uses the cloud_mask grid as the authoritative reference grid (20m native SCL grid).
        Aligns bands using WarpedVRT, computes normalized spectral difference,
        applies thresholding strictly to valid pixels, and writes water_mask.tif.
        """
        for p in (green_path, nir_path, cloud_mask_path):
            if not p.exists():
                raise FileNotFoundError(f"Input raster not found: {p}")

        output_water_mask_path.parent.mkdir(parents=True, exist_ok=True)

        # Open reference grid from cloud mask
        with rasterio.open(cloud_mask_path) as ref_src:
            ref_meta = ref_src.meta.copy()
            ref_crs = ref_src.crs
            ref_transform = ref_src.transform
            ref_width = ref_src.width
            ref_height = ref_src.height
            valid_mask = ref_src.read(1)  # 1 = valid, 0 = invalid

            # Resolution in meters for area estimation
            res_x, res_y = ref_src.res

            # Open Green (B03) and NIR (B08) and warp them onto the reference grid
            vrt_kwargs = {
                "crs": ref_crs,
                "transform": ref_transform,
                "width": ref_width,
                "height": ref_height,
                "resampling": Resampling.bilinear,
            }

            with rasterio.open(green_path) as src_g, rasterio.open(nir_path) as src_nir:
                with WarpedVRT(src_g, **vrt_kwargs) as vrt_g, WarpedVRT(src_nir, **vrt_kwargs) as vrt_nir:
                    green_arr = vrt_g.read(1).astype(np.float32)
                    nir_arr = vrt_nir.read(1).astype(np.float32)

                    # Usable pixels: valid from cloud mask, positive reflectance, finite values
                    usable = (valid_mask == 1) & (green_arr > 0) & (nir_arr > 0) & np.isfinite(green_arr) & np.isfinite(nir_arr)

                    # Compute spectral contrast: (Green - NIR) / (Green + NIR)
                    denom = green_arr + nir_arr
                    with np.errstate(divide="ignore", invalid="ignore"):
                        spectral_idx = np.where(denom > 0, (green_arr - nir_arr) / denom, -1.0)

                    # Binary water mask: 1 only where usable and index > threshold
                    is_water = usable & (spectral_idx > threshold)
                    water_mask = np.where(is_water, 1, 0).astype(np.uint8)

                    # Statistics
                    total_px = int(water_mask.size)
                    valid_px = int(np.sum(usable))
                    water_px = int(np.sum(water_mask == 1))

                    water_pct_valid = round((water_px / max(1, valid_px)) * 100.0, 2)
                    water_pct_total = round((water_px / max(1, total_px)) * 100.0, 2)

                    # Calculate area in sq km: pixel_count * (res_x * res_y in m^2) / 1e6
                    pixel_area_m2 = abs(float(res_x) * float(res_y))
                    area_sq_km = round((water_px * pixel_area_m2) / 1_000_000.0, 3)

                    # Write georeferenced GeoTIFF
                    ref_meta.update({
                        "dtype": "uint8",
                        "count": 1,
                        "nodata": 0,
                        "compress": "deflate",
                    })

                    with rasterio.open(output_water_mask_path, "w", **ref_meta) as dst:
                        dst.write(water_mask, 1)

                    return {
                        "output_path": output_water_mask_path,
                        "method": "Normalized Difference Spectral Segmentation (Green/NIR)",
                        "threshold": threshold,
                        "source_bands": ["B03", "B08"],
                        "total_pixels": total_px,
                        "valid_pixels_evaluated": valid_px,
                        "water_pixels": water_px,
                        "water_extent_percentage_of_valid": water_pct_valid,
                        "water_extent_percentage_of_total": water_pct_total,
                        "estimated_water_area_sq_km": area_sq_km,
                        "crs": str(ref_crs),
                        "transform": ref_transform,
                        "width": ref_width,
                        "height": ref_height,
                    }
