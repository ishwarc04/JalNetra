from abc import ABC, abstractmethod
from typing import List
from app.services.discovery.models import WaterBodyDiscoveryResult, GeocodedLocation


class WaterBodyProvider(ABC):
    """
    Abstract interface for water-body geographic data providers.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique provider identifier (e.g. 'osm')."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable provider description."""
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> List[WaterBodyDiscoveryResult]:
        """
        Search external provider for water bodies matching query.
        Returns a list of normalized WaterBodyDiscoveryResult items.
        """
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        """
        Lightweight health/readiness check for the provider.
        """
        pass

    @abstractmethod
    async def geocode_location(
        self,
        query: str,
        limit: int = 5,
    ) -> List[GeocodedLocation]:
        """
        Geocode a location query string into geographic coordinates.
        """
        pass

    @abstractmethod
    async def search_area(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        limit: int = 30,
    ) -> List[WaterBodyDiscoveryResult]:
        """
        Search for water bodies within a given radius (km) of a coordinate.
        """
        pass
