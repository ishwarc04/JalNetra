from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, List, Optional
from datetime import datetime
from app.services.satellite.models import NormalizedScene, NormalizedAsset


class SatelliteProvider(ABC):
    """
    Abstract interface for satellite data providers (e.g. Earth Search STAC, Copernicus Data Space, etc.).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier, e.g. 'earth_search'."""
        pass

    @property
    @abstractmethod
    def collection(self) -> str:
        """Target Sentinel-2 collection, e.g. 'sentinel-2-c1-l2a'."""
        pass

    @abstractmethod
    async def search_scenes(
        self,
        geometry: Optional[Dict] = None,
        bbox: Optional[List[float]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        max_cloud_cover: float = 30.0,
        limit: int = 10,
    ) -> List[NormalizedScene]:
        """
        Search for satellite scenes intersecting geometry or bbox within date range and cloud cover criteria.
        """
        pass

    @abstractmethod
    async def get_scene(self, external_scene_id: str) -> Optional[NormalizedScene]:
        """
        Retrieve a specific scene by its external ID.
        """
        pass

    @abstractmethod
    async def stream_asset_bytes(
        self,
        remote_url: str,
        chunk_size: int = 65536,
    ) -> AsyncGenerator[bytes, None]:
        """
        Streams binary data chunks for an asset from remote URL.
        """
        pass
