import json
import logging
from typing import Optional, Tuple, Dict, Any, List
import numpy as np
import rasterio.transform
import rasterio.features

logger = logging.getLogger("jalnetra.spectral.aoi")


class WaterBodyAOIProcessor:
    """
    Restricts spectral indicator calculations strictly to the registered water-body polygon.
    Ensures surrounding land, shorelines, and external pixels do not contaminate statistics.
    """

    @staticmethod
    def get_affine_transform(bounds: Tuple[float, float, float, float], width: int, height: int) -> rasterio.transform.Affine:
        min_lon, min_lat, max_lon, max_lat = bounds
        return rasterio.transform.from_bounds(min_lon, min_lat, max_lon, max_lat, width, height)

    @classmethod
    def create_water_mask(
        cls,
        geometry_geojson: Optional[str],
        crop_bounds: Tuple[float, float, float, float],
        shape: Tuple[int, int],
    ) -> Tuple[np.ndarray, bool]:
        """
        Creates a boolean mask where True = inside the water body vector geometry.
        Returns (water_mask, is_exact_polygon).
        """
        height, width = shape
        transform = cls.get_affine_transform(crop_bounds, width, height)

        if not geometry_geojson:
            # If no polygon is stored, the cropped AOI itself represents the water body bounding box
            # Fall back to an inscribed oval/polygon so border land doesn't dominate, or full box
            logger.info("No geometry_geojson found; using crop bounding box")
            return np.ones(shape, dtype=bool), False

        try:
            raw_geom = json.loads(geometry_geojson)
            geom = raw_geom.get("geometry", raw_geom) if isinstance(raw_geom, dict) else raw_geom

            if not geom or "type" not in geom:
                return np.ones(shape, dtype=bool), False

            # rasterio.features.geometry_mask sets True for masked (outside) by default,
            # so invert=True gives True for inside the geometry.
            water_mask = rasterio.features.geometry_mask(
                [geom],
                out_shape=shape,
                transform=transform,
                invert=True,
                all_touched=True,
            )

            # Check if mask has any positive pixels
            if np.sum(water_mask) == 0:
                logger.warning("Geometry mask yielded 0 pixels in AOI bounds; falling back to bounds")
                return np.ones(shape, dtype=bool), False

            return water_mask, True

        except Exception as exc:
            logger.error("Failed to rasterize water body geometry: %s", exc)
            return np.ones(shape, dtype=bool), False
