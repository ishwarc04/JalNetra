"""
Sentinel-2 Scene Classification Layer (SCL) Cloud and Shadow Masking.
Distinguishes usable clear surface pixels from clouds, cloud shadows, cirrus, snow, and invalid pixels.
Outputs a binary GeoTIFF valid mask:
  0 = invalid/masked (clouds, shadows, snow, nodata)
  1 = valid/usable (clear surface observations)
"""
from pathlib import Path
from typing import Dict, Any, Set, Tuple
import numpy as np
import rasterio
from rasterio.transform import Affine


# Sentinel-2 SCL Standard Class Definitions:
# 0 = No Data
# 1 = Saturated or defective
# 2 = Dark area pixels
# 3 = Cloud shadows
# 4 = Vegetation
# 5 = Not vegetated / bare soils
# 6 = Water
# 7 = Unclassified
# 8 = Cloud medium probability
# 9 = Cloud high probability
# 10 = Thin cirrus
# 11 = Snow or ice

DEFAULT_MASKED_SCL_CLASSES: Set[int] = {0, 1, 3, 8, 9, 10, 11}
CLOUD_SHADOW_SCL_CLASSES: Set[int] = {3, 8, 9, 10}


class CloudMaskGenerator:
    """Generates georeferenced valid-pixel masks from Sentinel-2 SCL rasters."""

    @staticmethod
    def generate_mask(
        scl_path: Path,
        output_mask_path: Path,
        masked_classes: Set[int] = DEFAULT_MASKED_SCL_CLASSES,
    ) -> Dict[str, Any]:
        """
        Reads the SCL GeoTIFF, classifies pixels, and writes a georeferenced binary GeoTIFF:
          0 = invalid / cloud / shadow / nodata
          1 = valid clear observation
        Returns metadata metrics.
        """
        if not scl_path.exists():
            raise FileNotFoundError(f"SCL raster not found at: {scl_path}")

        output_mask_path.parent.mkdir(parents=True, exist_ok=True)

        with rasterio.open(scl_path) as src:
            meta = src.meta.copy()
            scl_data = src.read(1)

            # Classify valid pixels
            is_masked = np.isin(scl_data, list(masked_classes))
            valid_mask = np.where(~is_masked, 1, 0).astype(np.uint8)

            # Cloud / shadow specific pixels for reporting
            cloud_shadow_mask = np.isin(scl_data, list(CLOUD_SHADOW_SCL_CLASSES))
            cloud_shadow_count = int(np.sum(cloud_shadow_mask))

            total_px = int(scl_data.size)
            valid_px = int(np.sum(valid_mask == 1))
            valid_pct = round((valid_px / max(1, total_px)) * 100.0, 2)
            cloud_shadow_pct = round((cloud_shadow_count / max(1, total_px)) * 100.0, 2)

            # Update GeoTIFF metadata for binary mask (uint8, nodata=0, deflate compressed)
            meta.update({
                "dtype": "uint8",
                "count": 1,
                "nodata": 0,
                "compress": "deflate",
            })

            # Write georeferenced GeoTIFF
            with rasterio.open(output_mask_path, "w", **meta) as dst:
                dst.write(valid_mask, 1)

            return {
                "output_path": output_mask_path,
                "total_pixels": total_px,
                "valid_pixels": valid_px,
                "cloud_shadow_pixels": cloud_shadow_count,
                "valid_pixel_percentage": valid_pct,
                "cloud_shadow_percentage": cloud_shadow_pct,
                "masked_classes": sorted(list(masked_classes)),
                "crs": str(src.crs),
                "transform": src.transform,
                "width": src.width,
                "height": src.height,
            }
