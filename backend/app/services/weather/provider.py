from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime


class WeatherProvider(ABC):
    """
    Abstract interface for future weather and climate data integration in JalNetra 2.0.
    Implementation will connect to real weather APIs in Phase 6.
    """

    @abstractmethod
    async def get_current_weather(self, lat: float, lon: float) -> Dict[str, Any]:
        """Fetches current real-time weather conditions for coordinates."""
        raise NotImplementedError("Weather API provider not configured in this phase.")

    @abstractmethod
    async def get_forecast(self, lat: float, lon: float, days: int = 7) -> Dict[str, Any]:
        """Fetches multi-day weather forecast for coordinates."""
        raise NotImplementedError("Weather API forecast not configured in this phase.")

    @abstractmethod
    async def get_historical_weather(
        self, lat: float, lon: float, start_date: datetime, end_date: datetime
    ) -> Dict[str, Any]:
        """Fetches historical weather data for correlation with satellite observation epochs."""
        raise NotImplementedError("Historical weather not configured in this phase.")
