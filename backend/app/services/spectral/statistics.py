import math
from typing import Dict, Any, Optional
import numpy as np


class SpectralStatistics:
    """
    Computes robust statistical metrics on valid, masked water pixels.
    Guarantees no NaN, Inf, or division-by-zero errors in returned results.
    """

    MIN_VALID_PIXELS = 30
    MIN_VALID_COVERAGE_PCT = 5.0

    @classmethod
    def calculate(
        cls,
        data: np.ndarray,
        valid_mask: np.ndarray,
        total_water_pixels: int,
    ) -> Dict[str, Any]:
        """
        Calculates mean, median, standard deviation, minimum, and maximum on valid pixels.
        Returns:
            dict with status, quality, statistics, and pixel metrics.
        """
        # Ensure finite data
        finite_valid_mask = valid_mask & np.isfinite(data)
        valid_count = int(np.sum(finite_valid_mask))
        total_pixels = max(total_water_pixels, 1)
        valid_pct = round((valid_count / total_pixels) * 100.0, 2)

        if valid_count < cls.MIN_VALID_PIXELS or valid_pct < cls.MIN_VALID_COVERAGE_PCT:
            return {
                "quality": "INSUFFICIENT",
                "quality_reason": (
                    f"Insufficient clear water pixels ({valid_count} pixels, {valid_pct}% coverage). "
                    "Cloud, shadow, or off-swath nodata prevents a reliable spectral indicator."
                ),
                "valid_pixel_count": valid_count,
                "total_water_pixels": total_water_pixels,
                "valid_pixel_percent": valid_pct,
                "mean": None,
                "median": None,
                "std": None,
                "minimum": None,
                "maximum": None,
                "value": None,
            }

        valid_values = data[finite_valid_mask].astype(np.float64)

        mean_val = float(np.mean(valid_values))
        median_val = float(np.median(valid_values))
        std_val = float(np.std(valid_values))
        min_val = float(np.min(valid_values))
        max_val = float(np.max(valid_values))

        # Check for non-finite values just in case
        if any(math.isnan(x) or math.isinf(x) for x in (mean_val, median_val, std_val, min_val, max_val)):
            return {
                "quality": "INSUFFICIENT",
                "quality_reason": "Numerical instability detected in valid pixel values.",
                "valid_pixel_count": valid_count,
                "total_water_pixels": total_water_pixels,
                "valid_pixel_percent": valid_pct,
                "mean": None,
                "median": None,
                "std": None,
                "minimum": None,
                "maximum": None,
                "value": None,
            }

        return {
            "quality": "GOOD" if valid_pct >= 70.0 else "LIMITED",
            "quality_reason": None if valid_pct >= 70.0 else f"Moderate valid coverage ({valid_pct}% clear water pixels).",
            "valid_pixel_count": valid_count,
            "total_water_pixels": total_water_pixels,
            "valid_pixel_percent": valid_pct,
            "mean": round(mean_val, 4),
            "median": round(median_val, 4),
            "std": round(std_val, 4),
            "minimum": round(min_val, 4),
            "maximum": round(max_val, 4),
            "value": round(median_val, 4),  # Use median as primary robust summary indicator
        }
