from typing import Dict, Any, Tuple, List, Optional
import math
import numpy as np


class SpectralAnomalyIndicator:
    """
    Surface Spectral Anomaly Indicator.
    Evaluates statistical divergence relative to the water body's historical baseline:
    z = (current_val - historical_mean) / historical_std
    Requires at least 3 historical observations for a valid baseline.
    """

    ID = "anomaly"
    LABEL = "Surface Spectral Anomaly"
    INDEX_NAME = "Z-Score Anomaly"
    REQUIRED_BANDS = ["B04", "B03"]  # Baseline index uses NDTI/reflectance
    FORMULA = "Z = (Obs_Value - Historical_Mean) / Historical_StdDev"
    DISCLAIMER = (
        "Measures unusual spectral behavior relative to historical observations of this specific water body. "
        "A statistical anomaly indicates deviation from typical baseline reflectance and does NOT by itself identify pollution or its root cause."
    )

    MIN_BASELINE_OBSERVATIONS = 3

    @classmethod
    def calculate_anomaly(
        cls, current_val: float, historical_values: List[float]
    ) -> Tuple[Optional[float], Optional[float], Optional[float], str, str, str]:
        """
        Calculates z-score anomaly against historical observations of the same water body.
        Returns:
            (z_score, hist_mean, hist_std, quality, classification, desc)
        """
        valid_hist = [float(v) for v in historical_values if v is not None and not math.isnan(v)]

        if len(valid_hist) < cls.MIN_BASELINE_OBSERVATIONS:
            return (
                None,
                round(float(np.mean(valid_hist)), 4) if valid_hist else None,
                round(float(np.std(valid_hist)), 4) if len(valid_hist) > 1 else None,
                "LIMITED",
                "BASELINE UNAVAILABLE",
                (
                    f"Baseline unavailable: {len(valid_hist)} of {cls.MIN_BASELINE_OBSERVATIONS} required historical "
                    "observations available for this water body. Acquire more dates to establish baseline."
                ),
            )

        hist_mean = float(np.mean(valid_hist))
        hist_std = float(np.std(valid_hist))

        # Standard deviation floor to avoid division by zero on uniform data
        if hist_std < 0.005:
            hist_std = 0.005

        z_score = float((current_val - hist_mean) / hist_std)
        z_abs = abs(z_score)

        if z_abs < 1.0:
            classification = "NORMAL"
            desc = "Surface reflectance aligns within 1 standard deviation of historical water-body baseline."
        elif z_abs < 2.0:
            classification = "WATCH"
            desc = f"Moderate statistical departure ({z_score:+.2f}σ) relative to historical baseline."
        else:
            classification = "HIGH ANOMALY"
            desc = f"Significant spectral divergence ({z_score:+.2f}σ ≥ 2σ) relative to historical baseline."

        return (
            round(z_score, 2),
            round(hist_mean, 4),
            round(hist_std, 4),
            "GOOD",
            classification,
            desc,
        )
