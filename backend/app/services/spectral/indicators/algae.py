from typing import Dict, Any, Tuple
import numpy as np
from PIL import Image
from app.services.spectral.resampling import resample_array


class AlgalActivityIndicator:
    """
    Floating Algae Index (FAI) / Surface Bloom Activity Proxy.
    Formula: FAI = R(B05) - [R(B04) + (R(B08) - R(B04)) * ( (705 - 665) / (842 - 665) )]
    Where B04 is Red (665 nm), B05 is Red Edge 1 (705 nm), and B08 is NIR (842 nm).
    Wavelength factor = (705 - 665) / (842 - 665) = 40 / 177 ≈ 0.2260.
    """

    ID = "fai"
    LABEL = "Algal Activity Proxy"
    INDEX_NAME = "FAI"
    REQUIRED_BANDS = ["B04", "B05", "B08"]
    FORMULA = "FAI = B05_RedEdge - [B04_Red + (B08_NIR - B04_Red) * 0.226]"
    DISCLAIMER = (
        "Optical surface-algae reflectance anomaly proxy. "
        "This optical signal does NOT confirm species, biomass, cyanobacterial toxin presence, or harmful algal blooms."
    )

    @classmethod
    def calculate(cls, b04: np.ndarray, b05: np.ndarray, b08: np.ndarray) -> np.ndarray:
        """Computes FAI array after resolution alignment."""
        # Align all to B04 shape (10m)
        target_shape = b04.shape
        if b05.shape != target_shape:
            b05 = resample_array(b05, target_shape, is_categorical=False)
        if b08.shape != target_shape:
            b08 = resample_array(b08, target_shape, is_categorical=False)

        # Scale DN to reflectance [0, 1] assuming Sentinel-2 L2A 10000 scale factor
        # If arrays are already scaled or raw DN, ratios remain consistent
        scale = 10000.0 if np.nanmax(b04) > 100.0 else 1.0

        r04 = b04.astype(np.float32) / scale
        r05 = b05.astype(np.float32) / scale
        r08 = b08.astype(np.float32) / scale

        # Baseline reflectance at 705 nm
        baseline = r04 + (r08 - r04) * 0.2260
        fai = r05 - baseline
        return fai

    @classmethod
    def classify(cls, value: float) -> Tuple[str, str]:
        """Maps FAI value to relative level and description."""
        if value < 0.00:
            return "LOW", "No significant optical surface scum or floating algal reflectance."
        elif value < 0.05:
            return "MODERATE", "Emerging surface spectral response / mild algal reflectance anomaly."
        else:
            return "HIGH", "Elevated surface algal activity / intense floating bloom reflectance."

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
        Low: Navy Blue -> Moderate: Seafoam -> High: Vibrant Neon Green.
        """
        h, w = index_arr.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)

        if bg_rgb is not None and bg_rgb.shape[:2] == (h, w):
            rgba[:, :, :3] = (bg_rgb[:, :, :3] * 0.45).astype(np.uint8)
            rgba[:, :, 3] = 255

        # Normalize FAI across [-0.04, 0.12] to [0, 1]
        norm = np.clip((index_arr - (-0.04)) / (0.12 - (-0.04)), 0.0, 1.0)

        # 0.0 -> Navy Blue (15, 30, 90)
        # 0.5 -> Seafoam / Teal (40, 160, 140)
        # 1.0 -> Bright Neon Green (50, 240, 60)
        r = np.where(norm < 0.5, 15 + norm * 2 * (40 - 15), 40 + (norm - 0.5) * 2 * (50 - 40))
        g = np.where(norm < 0.5, 30 + norm * 2 * (160 - 30), 160 + (norm - 0.5) * 2 * (240 - 160))
        b = np.where(norm < 0.5, 90 + norm * 2 * (140 - 90), 140 + (norm - 0.5) * 2 * (60 - 140))

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
