from typing import Dict, Any, Tuple
import numpy as np
from PIL import Image
from app.services.spectral.resampling import resample_array


class ChlorophyllIndicator:
    """
    Normalized Difference Chlorophyll Index (NDCI) / Chlorophyll-a Proxy.
    Formula: NDCI = (B05 - B04) / (B05 + B04)
    Where B05 is Red Edge 1 (705 nm) and B04 is Red (665 nm).
    """

    ID = "ndci"
    LABEL = "Chlorophyll-a Proxy"
    INDEX_NAME = "NDCI"
    REQUIRED_BANDS = ["B04", "B05"]
    FORMULA = "NDCI = (B05_RedEdge - B04_Red) / (B05_RedEdge + B04_Red)"
    DISCLAIMER = (
        "Satellite spectral proxy related to photosynthetic pigment response. "
        "This is an uncalibrated remote-sensing index, NOT a laboratory chlorophyll-a concentration in mg/m³."
    )

    @classmethod
    def calculate(cls, b04: np.ndarray, b05: np.ndarray) -> np.ndarray:
        """Computes NDCI array after aligning resolutions."""
        # Align B05 (20m) to B04 (10m) shape if needed
        if b05.shape != b04.shape:
            b05 = resample_array(b05, b04.shape, is_categorical=False)

        b05_f = b05.astype(np.float32)
        b04_f = b04.astype(np.float32)

        denom = b05_f + b04_f
        numer = b05_f - b04_f

        with np.errstate(divide="ignore", invalid="ignore"):
            ndci = np.where(denom > 0, numer / denom, np.nan)
        return ndci

    @classmethod
    def classify(cls, value: float) -> Tuple[str, str]:
        """Maps NDCI value to relative level and description."""
        if value < -0.10:
            return "LOW", "Low photosynthetic pigment signal / oligotrophic surface water."
        elif value < 0.10:
            return "MODERATE", "Moderate photosynthetic pigment reflectance / mesotrophic response."
        else:
            return "HIGH", "Elevated chlorophyll-a optical signal / eutrophic response."

    @classmethod
    def render_preview(
        cls,
        index_arr: np.ndarray,
        water_mask: np.ndarray,
        valid_mask: np.ndarray,
        output_path: str,
        bg_rgb: np.ndarray = None,
    ) -> None:
        """
        Renders an RGBA preview colormap.
        Low: Deep Blue -> Moderate: Leaf Green -> High: Bright Emerald/Red.
        """
        h, w = index_arr.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)

        if bg_rgb is not None and bg_rgb.shape[:2] == (h, w):
            rgba[:, :, :3] = (bg_rgb[:, :, :3] * 0.45).astype(np.uint8)
            rgba[:, :, 3] = 255

        # Normalize NDCI across [-0.25, 0.35] to [0, 1]
        norm = np.clip((index_arr - (-0.25)) / (0.35 - (-0.25)), 0.0, 1.0)

        # 0.0 -> Blue (30, 90, 190)
        # 0.5 -> Green (40, 180, 70)
        # 1.0 -> Amber / Red (220, 60, 40)
        r = np.where(norm < 0.5, 30 + norm * 2 * (40 - 30), 40 + (norm - 0.5) * 2 * (220 - 40))
        g = np.where(norm < 0.5, 90 + norm * 2 * (180 - 90), 180 + (norm - 0.5) * 2 * (60 - 180))
        b = np.where(norm < 0.5, 190 + norm * 2 * (70 - 190), 70 + (norm - 0.5) * 2 * (40 - 70))

        paint_mask = water_mask & valid_mask & np.isfinite(index_arr)
        rgba[paint_mask, 0] = r[paint_mask].astype(np.uint8)
        rgba[paint_mask, 1] = g[paint_mask].astype(np.uint8)
        rgba[paint_mask, 2] = b[paint_mask].astype(np.uint8)
        rgba[paint_mask, 3] = 255

        cloud_mask = water_mask & (~valid_mask)
        rgba[cloud_mask, 0] = 160
        rgba[cloud_mask, 1] = 160
        rgba[cloud_mask, 2] = 170
        rgba[cloud_mask, 3] = 200

        im = Image.fromarray(rgba, "RGBA")
        im.save(output_path, "PNG", optimize=True)
