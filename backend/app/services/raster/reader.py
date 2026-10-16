"""
Low-level GeoTIFF metadata inspection and reading utilities using Rasterio.
"""
from pathlib import Path
from typing import Dict, Any, Optional
import rasterio
from rasterio.warp import transform_bounds


class RasterReader:
    """Safely inspects and extracts metadata from local GeoTIFF files."""

    @staticmethod
    def inspect_file(file_path: Path) -> Dict[str, Any]:
        """
        Inspects a GeoTIFF raster file and extracts CRS, dimensions,
        native bounds, WGS84 bounds, resolution, and nodata value.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Raster file not found: {file_path}")

        with rasterio.open(file_path) as src:
            crs_str = str(src.crs) if src.crs else None
            bounds = src.bounds
            native_bounds = {
                "left": bounds.left,
                "bottom": bounds.bottom,
                "right": bounds.right,
                "top": bounds.top,
            }

            # Transform to EPSG:4326 if valid CRS is present
            geo_bounds = None
            if src.crs:
                try:
                    w, s, e, n = transform_bounds(src.crs, "EPSG:4326", *bounds)
                    geo_bounds = {
                        "west": float(w),
                        "south": float(s),
                        "east": float(e),
                        "north": float(n),
                    }
                except Exception:
                    pass

            # Calculate pixel resolution (x, y)
            res = src.res if hasattr(src, "res") else (None, None)
            res_val = float(res[0]) if res and res[0] is not None else None

            return {
                "crs": crs_str,
                "width": src.width,
                "height": src.height,
                "bands": src.count,
                "dtypes": [str(d) for d in src.dtypes],
                "nodata": float(src.nodata) if src.nodata is not None else None,
                "native_bounds": native_bounds,
                "geographic_bounds": geo_bounds,
                "resolution_meters": res_val,
            }
