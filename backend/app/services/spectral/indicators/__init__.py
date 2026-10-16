from app.services.spectral.indicators.turbidity import TurbidityIndicator
from app.services.spectral.indicators.chlorophyll import ChlorophyllIndicator
from app.services.spectral.indicators.algae import AlgalActivityIndicator
from app.services.spectral.indicators.anomaly import SpectralAnomalyIndicator

INDICATOR_REGISTRY = {
    TurbidityIndicator.ID: TurbidityIndicator,
    ChlorophyllIndicator.ID: ChlorophyllIndicator,
    AlgalActivityIndicator.ID: AlgalActivityIndicator,
    SpectralAnomalyIndicator.ID: SpectralAnomalyIndicator,
}

__all__ = [
    "TurbidityIndicator",
    "ChlorophyllIndicator",
    "AlgalActivityIndicator",
    "SpectralAnomalyIndicator",
    "INDICATOR_REGISTRY",
]
