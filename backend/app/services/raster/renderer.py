"""
RGB Raster Alignment and Visualization Renderer.
Reprojects Sentinel-2 B04 (Red), B03 (Green), and B02 (Blue) GeoTIFFs to EPSG:4326,
aligns grids, handles NoData/invalid pixels, performs percentile contrast stretching,
and renders an RGBA PNG for Leaflet ImageOverlay.
"""
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, Union
import numpy as np
from PIL import Image
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from app.services.raster.models import GeoBounds


class RGBRenderer:
    """Renders aligned, reprojected, contrast-stretched RGB visualizations from Sentinel-2 bands."""

    @staticmethod
    def validate_rgb_quality(
        r_arr: np.ndarray,
        g_arr: np.ndarray,
        b_arr: np.ndarray,
        valid_mask: np.ndarray,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Calculates image quality metrics and checks if the RGB output is visually usable.
        Rejects blank, zero-variance, off-swath nodata, and solid whiteout cloud images.
        """
        valid_count = int(np.sum(valid_mask))
        total_count = int(valid_mask.size)
        valid_pct = (valid_count / max(total_count, 1)) * 100.0

        if valid_pct < 15.0:
            return (
                False,
                f"Insufficient valid pixels ({valid_pct:.1f}% valid data in AOI, off-swath or nodata)",
                {"valid_pixel_pct": round(valid_pct, 2), "reason": "OFF_SWATH_NODATA"},
            )

        valid_r = r_arr[valid_mask]
        valid_g = g_arr[valid_mask]
        valid_b = b_arr[valid_mask]

        r_std = float(np.std(valid_r))
        g_std = float(np.std(valid_g))
        b_std = float(np.std(valid_b))

        # Check for completely flat / uniform / zero variance
        if r_std < 2.0 and g_std < 2.0 and b_std < 2.0:
            return (
                False,
                "Zero-variance blank image (completely uniform/flat values)",
                {"valid_pixel_pct": round(valid_pct, 2), "std": (r_std, g_std, b_std), "reason": "ZERO_VARIANCE_BLANK"},
            )

        # Check for extreme dark/black
        mean_val = float((np.mean(valid_r) + np.mean(valid_g) + np.mean(valid_b)) / 3.0)
        if mean_val < 3.0:
            return (
                False,
                f"Extreme dark/black image (mean surface reflectance {mean_val:.1f} DN < 3)",
                {"valid_pixel_pct": round(valid_pct, 2), "mean_reflectance": round(mean_val, 1), "reason": "EXTREME_DARK"},
            )

        # Check for solid cloud whiteout saturation (> 8000 DN on all 3 channels)
        whiteout_mask = (valid_r > 8000) & (valid_g > 8000) & (valid_b > 8000)
        whiteout_ratio = float(np.mean(whiteout_mask))
        if whiteout_ratio > 0.90:
            return (
                False,
                f"Solid cloud whiteout ({whiteout_ratio * 100.0:.1f}% saturated cloud pixels)",
                {"valid_pixel_pct": round(valid_pct, 2), "whiteout_ratio": round(whiteout_ratio, 3), "reason": "SOLID_CLOUD_WHITEOUT"},
            )

        metrics = {
            "valid_pixel_pct": round(valid_pct, 2),
            "mean_reflectance": round(mean_val, 1),
            "std": (round(r_std, 1), round(g_std, 1), round(b_std, 1)),
            "whiteout_ratio": round(whiteout_ratio, 3),
        }
        return (True, "VALID", metrics)

    @staticmethod
    def render_rgb(
        red_path: Union[Path, str],
        green_path: Union[Path, str],
        blue_path: Union[Path, str],
        output_png_path: Path,
        max_dimension: int = 1024,
        lower_percentile: float = 2.0,
        upper_percentile: float = 98.0,
        crop_bounds: Optional[Tuple[float, float, float, float]] = None,
        raise_on_unusable: bool = False,
    ) -> Dict[str, Any]:
        """
        Takes red (B04), green (B03), and blue (B02) GeoTIFFs (local Path or remote URL),
        reprojects them on the fly to EPSG:4326 using WarpedVRT,
        crops to crop_bounds (west, south, east, north) in EPSG:4326,
        applies percentile-based contrast stretch to valid pixels with natural color tone mapping,
        validates image quality, masks nodata pixels, and saves an RGBA PNG / high-quality JPEG.

        Returns geographic bounds (EPSG:4326), dimensions, and image quality metrics.
        """
        # Validate local paths if provided
        for p in (red_path, green_path, blue_path):
            if isinstance(p, Path) or (isinstance(p, str) and not p.startswith("http")):
                local_p = Path(p)
                if not local_p.exists():
                    raise FileNotFoundError(f"Band file not found: {p}")

        # Check if remote URLs are used
        is_remote = any(
            isinstance(p, str) and (p.startswith("http://") or p.startswith("https://"))
            for p in (red_path, green_path, blue_path)
        )

        raster_env_kwargs = {}
        if is_remote:
            raster_env_kwargs = {
                "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
                "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
            }

        with rasterio.Env(**raster_env_kwargs):
            # Open bands
            with rasterio.open(str(red_path)) as src_r, \
                 rasterio.open(str(green_path)) as src_g, \
                 rasterio.open(str(blue_path)) as src_b:

                # Use WarpedVRT to reproject all 3 bands to EPSG:4326 on the fly
                vrt_kwargs = {"crs": "EPSG:4326", "resampling": Resampling.bilinear}
                with WarpedVRT(src_r, **vrt_kwargs) as vrt_r, \
                     WarpedVRT(src_g, **vrt_kwargs) as vrt_g, \
                     WarpedVRT(src_b, **vrt_kwargs) as vrt_b:

                    window = None
                    if crop_bounds:
                        cw, cs, ce, cn = crop_bounds
                        # Clamp crop bounds to the raster's extent
                        rw, rs, re, rn = vrt_r.bounds
                        int_w = max(cw, rw)
                        int_s = max(cs, rs)
                        int_e = min(ce, re)
                        int_n = min(cn, rn)

                        if int_e > int_w and int_n > int_s:
                            from rasterio.windows import from_bounds
                            window = from_bounds(int_w, int_s, int_e, int_n, transform=vrt_r.transform)
                            win_bounds = rasterio.windows.bounds(window, vrt_r.transform)
                            geo_bounds = GeoBounds(
                                west=float(win_bounds[0]),
                                south=float(win_bounds[1]),
                                east=float(win_bounds[2]),
                                north=float(win_bounds[3]),
                            )
                            target_width = max(1, int(round(window.width)))
                            target_height = max(1, int(round(window.height)))
                        else:
                            window = None

                    if window is None:
                        bounds = vrt_r.bounds
                        geo_bounds = GeoBounds(
                            west=float(bounds.left),
                            south=float(bounds.bottom),
                            east=float(bounds.right),
                            north=float(bounds.top),
                        )
                        target_width = vrt_r.width
                        target_height = vrt_r.height

                    # Determine output grid dimensions respecting aspect ratio.
                    # If windowed AOI is smaller than max_dimension, preserve 100% native resolution
                    if window is not None and target_width <= max_dimension and target_height <= max_dimension:
                        out_w = target_width
                        out_h = target_height
                        read_kwargs = {"window": window}
                    else:
                        aspect = target_width / max(1, target_height)
                        if aspect >= 1.0:
                            out_w = max_dimension
                            out_h = max(1, int(round(max_dimension / aspect)))
                        else:
                            out_w = max(1, int(round(max_dimension * aspect)))
                            out_h = max_dimension
                        read_kwargs = {"out_shape": (out_h, out_w), "resampling": Resampling.bilinear}
                        if window is not None:
                            read_kwargs["window"] = window

                    r_arr = vrt_r.read(1, **read_kwargs).astype(np.float32)
                    g_arr = vrt_g.read(1, **read_kwargs).astype(np.float32)
                    b_arr = vrt_b.read(1, **read_kwargs).astype(np.float32)

                    # Identify valid pixels: finite, not nodata, and positive
                    valid_mask = (
                        np.isfinite(r_arr) & (r_arr > 0) &
                        np.isfinite(g_arr) & (g_arr > 0) &
                        np.isfinite(b_arr) & (b_arr > 0)
                    )

                    # Apply nodata checks if defined on sources
                    for src, arr in ((src_r, r_arr), (src_g, g_arr), (src_b, b_arr)):
                        if src.nodata is not None:
                            valid_mask &= (arr != src.nodata)

                    # Validate visual quality
                    is_valid, quality_reason, quality_metrics = RGBRenderer.validate_rgb_quality(
                        r_arr, g_arr, b_arr, valid_mask
                    )
                    if not is_valid and raise_on_unusable:
                        raise ValueError(f"UNUSABLE VISUAL OUTPUT: {quality_reason}")

                    # Apply contrast stretch on valid pixels with natural tone mapping
                    stretched_channels = []
                    for channel_arr in (r_arr, g_arr, b_arr):
                        valid_vals = channel_arr[valid_mask]
                        if len(valid_vals) > 0:
                            p_low = max(0.0, float(np.percentile(valid_vals, lower_percentile)))
                            p_high = float(np.percentile(valid_vals, upper_percentile))
                            # Cap p_high to prevent bright cloud saturated pixels from crushing dark lake tones
                            p_high = min(p_high, 4500.0)
                            p_high = max(p_high, p_low + 10.0)

                            norm = np.clip((channel_arr - p_low) / (p_high - p_low), 0.0, 1.0)
                            # Subtle gamma expansion (1.15) to bring out surface water details
                            gamma_stretched = np.power(norm, 1.0 / 1.15) * 255.0
                            stretched = gamma_stretched.astype(np.uint8)
                        else:
                            stretched = np.zeros_like(channel_arr, dtype=np.uint8)
                        stretched_channels.append(stretched)

                    # Set alpha channel: 255 for valid data, 0 for off-swath/nodata
                    alpha = np.where(valid_mask, 255, 0).astype(np.uint8)

                    # Stack RGBA (Red=B04, Green=B03, Blue=B02, Alpha)
                    rgba = np.stack(
                        [stretched_channels[0], stretched_channels[1], stretched_channels[2], alpha],
                        axis=-1,
                    )

                    # Ensure output directory exists
                    output_png_path.parent.mkdir(parents=True, exist_ok=True)

                    img = Image.fromarray(rgba)
                    if output_png_path.suffix.lower() in (".jpg", ".jpeg"):
                        # Create RGB composite for JPEG with neutral nodata background
                        bg = Image.new("RGB", img.size, (240, 240, 240))
                        bg.paste(img, mask=img.split()[3])
                        bg.save(output_png_path, format="JPEG", quality=92, optimize=True)
                    else:
                        img.save(output_png_path, format="PNG", optimize=True)

                    return {
                        "output_path": output_png_path,
                        "width": out_w,
                        "height": out_h,
                        "bounds": geo_bounds,
                        "crs": "EPSG:4326",
                        "quality_valid": is_valid,
                        "quality_reason": quality_reason,
                        "quality_metrics": quality_metrics,
                    }
