import time
import logging
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger("jalnetra.weather.cache")

# Default TTLs in seconds
DEFAULT_CURRENT_TTL = 1800   # 30 minutes
DEFAULT_FORECAST_TTL = 10800  # 3 hours


class WeatherCache:
    """
    In-memory weather cache supporting separate TTLs for current conditions and forecasts,
    with stale-data fallback support during upstream network hiccups.
    """

    def __init__(self, current_ttl: int = DEFAULT_CURRENT_TTL, forecast_ttl: int = DEFAULT_FORECAST_TTL):
        self.current_ttl = current_ttl
        self.forecast_ttl = forecast_ttl
        # Key: (water_body_id or coord_key) -> (data, timestamp, ttl)
        self._cache: Dict[str, Tuple[Dict[str, Any], float, float]] = {}

    def _make_key(self, prefix: str, identifier: str) -> str:
        return f"{prefix}:{identifier}"

    def get(self, prefix: str, identifier: str, allow_stale: bool = False) -> Optional[Dict[str, Any]]:
        key = self._make_key(prefix, identifier)
        entry = self._cache.get(key)
        if not entry:
            return None

        data, timestamp, ttl = entry
        age = time.time() - timestamp

        if age <= ttl:
            return data

        if allow_stale:
            logger.info("Serving stale weather cache for key %s (age=%.1fs)", key, age)
            return data

        return None

    def set(self, prefix: str, identifier: str, data: Dict[str, Any], is_forecast: bool = True):
        key = self._make_key(prefix, identifier)
        ttl = self.forecast_ttl if is_forecast else self.current_ttl
        self._cache[key] = (data, time.time(), ttl)

    def clear(self):
        self._cache.clear()

    def remove(self, prefix: str, identifier: str):
        key = self._make_key(prefix, identifier)
        self._cache.pop(key, None)


# Singleton weather cache instance
weather_cache = WeatherCache()
