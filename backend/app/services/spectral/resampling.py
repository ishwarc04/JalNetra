import numpy as np
from PIL import Image


def resample_array(source_arr: np.ndarray, target_shape: tuple[int, int], is_categorical: bool = False) -> np.ndarray:
    """
    Resamples a 2D numpy array to target_shape (height, width).
    Uses nearest-neighbor for categorical masks (like SCL) and bilinear for continuous bands.
    """
    if source_arr.shape == target_shape:
        return source_arr

    target_h, target_w = target_shape
    resample_mode = Image.Resampling.NEAREST if is_categorical else Image.Resampling.BILINEAR

    if np.issubdtype(source_arr.dtype, np.floating):
        # Handle floating point continuous arrays
        # Preserve NaNs if present
        nan_mask = np.isnan(source_arr)
        clean_arr = np.nan_to_num(source_arr, nan=0.0)
        im = Image.fromarray(clean_arr.astype(np.float32))
        resized = im.resize((target_w, target_h), resample=resample_mode)
        out = np.array(resized, dtype=np.float32)

        if np.any(nan_mask):
            mask_im = Image.fromarray(nan_mask.astype(np.uint8))
            resized_mask = np.array(mask_im.resize((target_w, target_h), resample=Image.Resampling.NEAREST)) > 0
            out[resized_mask] = np.nan
        return out
    else:
        # Integer / categorical arrays
        im = Image.fromarray(source_arr)
        resized = im.resize((target_w, target_h), resample=resample_mode)
        return np.array(resized, dtype=source_arr.dtype)
