from typing import Dict, Any, Tuple
import numpy as np
from PIL import Image


class TurbidityIndicator:
    """
    Normalized Difference Turbidity Index (NDTI) / Suspended Sediment Proxy.
    Formula: NDTI = (B04 - B03) / (B04 + B03)
    Where B04 is Red (665 nm) and B03 is Green (560 nm).
    """

    ID = "ndti"
    LABEL = "Turbidity / Sediment Proxy"
    INDEX_NAME = "NDTI"
    REQUIRED_BANDS = ["B04", "B03"]
    FORMULA = "NDTI = (B04_Red - B03_Green) / (B04_Red + B03_Green)"
    DISCLAIMER = (
        "Satellite optical proxy related to suspended particulate and sediment scattering. "
        "This is an uncalibrated remote-sensing proxy, NOT a laboratory Nephelometric Turbidity Unit (NTU) measurement."
    )

    @classmethod
    def calculate(cls, b04: np.ndarray, b03: np.ndarray) -> np.ndarray:
        """Computes NDTI array with zero-division safety."""
        b04_f = b04.astype(np.float32)
        b03_f = b03.astype(np.float32)

        denom = b04_f + b03_f
        numer = b04_f - b03_f

        # Safe division
        with np.errstate(divide="ignore", invalid="ignore"):
            ndti = np.where(denom > 0, numer / denom, np.nan)
        return ndti

    @classmethod
    def classify(cls, value: float) -> Tuple[str, str]:
        """Maps NDTI value to relative level and description."""
        if value < -0.05:
            return "LOW", "Low suspended sediment / relatively clear surface water."
        elif value < 0.15:
            return "MODERATE", "Moderate suspended particulate matter and sediment scattering."
        else:
            return "HIGH", "High suspended sediment and elevated optical turbidity."

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
        Renders a lightweight RGBA preview colormap of the water body.
        Low: Cyan/Blue -> Moderate: Amber/Yellow -> High: Terracotta/Brown.
        """
        h, w = index_arr.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)

        # If background RGB is provided, use it as dim backdrop for context
        if bg_rgb is not None and bg_rgb.shape[:2] == (h, w):
            rgba[:, :, :3] = (bg_rgb[:, :, :3] * 0.45).astype(np.uint8)
            rgba[:, :, 3] = 255
        else:
            rgba[:, :, 3] = 0

        # Normalize NDTI across typical range [-0.2, 0.4] to [0, 1]
        norm = np.clip((index_arr - (-0.2)) / (0.4 - (-0.2)), 0.0, 1.0)

        # Color ramp
        # 0.0 -> Deep Blue (20, 80, 180)
        # 0.5 -> Amber Yellow (235, 180, 30)
        # 1.0 -> Brick Red / Brown (180, 50, 20)
        r = np.where(norm < 0.5, 20 + norm * 2 * (235 - 20), 235 + (norm - 0.5) * 2 * (180 - 235))
        g = np.where(norm < 0.5, 80 + norm * 2 * (180 - 80), 180 + (norm - 0.5) * 2 * (50 - 180))
        b = np.where(norm < 0.5, 180 + norm * 2 * (30 - 180), 30 + (norm - 0.5) * 2 * (20 - 30))

        # Apply to valid water pixels
        paint_mask = water_mask & valid_mask & np.isfinite(index_arr)
        rgba[paint_mask, 0] = r[paint_mask].astype(np.uint8)
        rgba[paint_mask, 1] = g[paint_mask].astype(np.uint8)
        rgba[paint_mask, 2] = b[paint_mask].astype(np.uint8)
        rgba[paint_mask, 3] = 255

        # Cloud / invalid water pixels: white/grey hatching
        cloud_mask = water_mask & (~valid_mask)
        rgba[cloud_mask, 0] = 160
        rgba[cloud_mask, 1] = 160
        rgba[cloud_mask, 2] = 170
        rgba[cloud_mask, 3] = 200

        im = Image.fromarray(rgba, "RGBA")
        im.save(output_path, "PNG", optimize=True)
