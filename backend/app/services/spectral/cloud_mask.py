from typing import Optional, Tuple
import numpy as np


class SCLCloudMasker:
    """
    Cloud and invalid pixel masking using Sentinel-2 Scene Classification Layer (SCL).
    """

    # Excluded SCL values:
    # 0 = NO_DATA, 1 = SATURATED_OR_DEFECTIVE, 3 = CLOUD_SHADOWS,
    # 8 = CLOUD_MEDIUM_PROBABILITY, 9 = CLOUD_HIGH_PROBABILITY, 10 = THIN_CIRRUS, 11 = SNOW_ICE
    INVALID_SCL_CLASSES = {0, 1, 3, 8, 9, 10, 11}
    CLOUD_OR_SHADOW_CLASSES = {3, 8, 9, 10}

    @classmethod
    def create_mask(cls, scl_arr: Optional[np.ndarray], shape: Tuple[int, int]) -> Tuple[np.ndarray, float, bool]:
        """
        Creates a boolean mask indicating clear, valid pixels.
        Returns: (clear_pixel_mask, cloud_pixel_percent, is_scl_available)
        clear_pixel_mask: True where pixel is NOT cloud, shadow, or defective nodata.
        """
        if scl_arr is None:
            # SCL is unavailable -> All pixels considered unmasked, flagged as LIMITED quality
            return np.ones(shape, dtype=bool), 0.0, False

        # Ensure correct shape
        if scl_arr.shape != shape:
            from app.services.spectral.resampling import resample_array
            scl_arr = resample_array(scl_arr, shape, is_categorical=True)

        is_invalid = np.isin(scl_arr, list(cls.INVALID_SCL_CLASSES))
        is_cloud_or_shadow = np.isin(scl_arr, list(cls.CLOUD_OR_SHADOW_CLASSES))

        total_pixels = scl_arr.size
        cloud_pixels = int(np.sum(is_cloud_or_shadow))
        cloud_pct = round((cloud_pixels / max(total_pixels, 1)) * 100.0, 2)

        clear_mask = ~is_invalid
        return clear_mask, cloud_pct, True
