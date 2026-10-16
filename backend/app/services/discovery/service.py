import json
import logging
import math
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import settings
from app.db.models.water_body import WaterBody
from app.db.repositories.water_body_repository import WaterBodyRepository
from app.schemas.water_body import WaterBodyCreate, WaterBodyRead
from app.services.discovery.base import WaterBodyProvider
from app.services.discovery.cache import DiscoveryCacheService
from app.services.discovery.models import (
    WaterBodyDiscoveryResult,
    DiscoverySearchResponse,
    ProviderStatus,
    GeocodedLocation,
    LocationSearchResponse,
    SearchCenter,
    SearchBoundingBox,
    AreaDiscoveryResponse,
    BatchImportRequest,
    BatchImportItemResult,
    BatchImportResponse,
)
from app.services.discovery.providers.osm import OpenStreetMapProvider

logger = logging.getLogger("jalnetra.discovery.service")


class DiscoveryProviderError(Exception):
    """Raised when an external discovery provider fails or is unreachable."""
    def __init__(self, message: str, code: str = "DISCOVERY_PROVIDER_UNAVAILABLE"):
        super().__init__(message)
        self.code = code
        self.message = message


class WaterBodyDiscoveryService:
    """
    High-level discovery orchestrator coordinating:
    - Provider abstraction and selection
    - Caching lookup and storage
    - In-memory result deduplication
    - Import to persistent WaterBody repository with duplicate protection
    """

    def __init__(
        self,
        db: Session,
        providers: Optional[Dict[str, WaterBodyProvider]] = None,
    ):
        self.db = db
        self.repo = WaterBodyRepository(db)
        self.cache = DiscoveryCacheService(db)

        # Register providers
        if providers is not None:
            self.providers = providers
        else:
            osm_provider = OpenStreetMapProvider()
            self.providers = {osm_provider.name: osm_provider}

    def list_providers(self) -> List[ProviderStatus]:
        results: List[ProviderStatus] = []
        for name, prov in self.providers.items():
            results.append(
                ProviderStatus(
                    name=name,
                    enabled=settings.WATERBODY_DISCOVERY_ENABLED,
                    status="available" if settings.WATERBODY_DISCOVERY_ENABLED else "disabled",
                    description=prov.description,
                )
            )
        return results

    async def search(
        self,
        query: str,
        limit: int = 10,
        provider_name: Optional[str] = None,
    ) -> DiscoverySearchResponse:
        query = query.strip()
        if not query:
            return DiscoverySearchResponse(
                query="",
                provider=provider_name or settings.WATERBODY_DISCOVERY_PROVIDER,
                results=[],
            )

        limit = min(max(1, limit), 20)
        target_provider_name = (
            provider_name or settings.WATERBODY_DISCOVERY_PROVIDER
        ).lower()

        if target_provider_name not in self.providers:
            raise DiscoveryProviderError(
                f"Discovery provider '{target_provider_name}' is not registered.",
                code="UNKNOWN_PROVIDER",
            )

        provider = self.providers[target_provider_name]

        # 1. Cache lookup
        cache_key = self.cache.build_cache_key(target_provider_name, query, limit)
        cached_raw = self.cache.get(cache_key)
        if cached_raw is not None:
            logger.info("Discovery cache hit for '%s'", cache_key)
            cached_results = [
                WaterBodyDiscoveryResult.model_validate(item) for item in cached_raw
            ]
            return DiscoverySearchResponse(
                query=query,
                provider=target_provider_name,
                results=cached_results,
            )

        # 2. Query provider
        logger.info("Querying external provider '%s' for '%s'", target_provider_name, query)
        try:
            raw_results = await provider.search(query, limit=limit)
        except Exception as exc:
            logger.error("Provider query failed for '%s': %s", query, exc)
            raise DiscoveryProviderError(
                f"The water-body discovery provider '{target_provider_name}' is temporarily unavailable: {str(exc)}",
                code="DISCOVERY_PROVIDER_UNAVAILABLE",
            )

        # 3. Deduplicate provider results in-memory
        deduped_results = self.deduplicate_results(raw_results)

        # 4. Save to cache
        cache_data = [item.model_dump() for item in deduped_results]
        self.cache.set(cache_key, target_provider_name, query, cache_data)

        return DiscoverySearchResponse(
            query=query,
            provider=target_provider_name,
            results=deduped_results,
        )

    async def geocode_location(
        self,
        query: str,
        limit: int = 5,
        provider_name: Optional[str] = None,
    ) -> LocationSearchResponse:
        query = query.strip()
        if not query:
            return LocationSearchResponse(query="", results=[])

        limit = min(max(1, limit), 10)
        target_provider_name = (
            provider_name or settings.WATERBODY_DISCOVERY_PROVIDER
        ).lower()

        if target_provider_name not in self.providers:
            raise DiscoveryProviderError(
                f"Discovery provider '{target_provider_name}' is not registered.",
                code="UNKNOWN_PROVIDER",
            )

        provider = self.providers[target_provider_name]

        # 1. Cache check
        cache_key = f"geocode:{target_provider_name}:{query.lower()}:{limit}"
        cached_raw = self.cache.get(cache_key)
        if cached_raw is not None:
            logger.info("Geocoding cache hit for '%s'", cache_key)
            cached_results = [
                GeocodedLocation.model_validate(item) for item in cached_raw
            ]
            return LocationSearchResponse(query=query, results=cached_results)

        # 2. Query provider
        logger.info("Geocoding query '%s' via '%s'", query, target_provider_name)
        try:
            results = await provider.geocode_location(query, limit=limit)
        except Exception as exc:
            logger.error("Geocoding failed for '%s': %s", query, exc)
            raise DiscoveryProviderError(
                f"Geocoding service is temporarily unavailable: {str(exc)}",
                code="GEOCODING_UNAVAILABLE",
            )

        # 3. Cache results
        cache_data = [item.model_dump() for item in results]
        self.cache.set(cache_key, target_provider_name, query, cache_data)

        return LocationSearchResponse(query=query, results=results)

    async def search_area(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 1.0,
        limit: int = 30,
        query_location: Optional[str] = None,
        provider_name: Optional[str] = None,
    ) -> AreaDiscoveryResponse:
        # Validate coordinates and radius
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            raise ValueError(f"Invalid latitude/longitude: ({latitude}, {longitude})")
        if radius_km <= 0 or radius_km > 50.0:
            raise ValueError("radius_km must be between 0.1 and 50.0")

        limit = min(max(1, limit), 60)
        target_provider_name = (
            provider_name or settings.WATERBODY_DISCOVERY_PROVIDER
        ).lower()

        if target_provider_name not in self.providers:
            raise DiscoveryProviderError(
                f"Discovery provider '{target_provider_name}' is not registered.",
                code="UNKNOWN_PROVIDER",
            )

        provider = self.providers[target_provider_name]

        # Calculate bounding box
        d_lat = radius_km / 111.0
        d_lon = radius_km / (111.0 * max(0.01, math.cos(math.radians(latitude))))
        bbox = SearchBoundingBox(
            min_lat=round(latitude - d_lat, 6),
            min_lon=round(longitude - d_lon, 6),
            max_lat=round(latitude + d_lat, 6),
            max_lon=round(longitude + d_lon, 6),
        )

        center = SearchCenter(
            latitude=round(latitude, 6),
            longitude=round(longitude, 6),
        )

        # 1. Cache check
        cache_key = f"area:{target_provider_name}:{round(latitude, 4)}:{round(longitude, 4)}:{round(radius_km, 2)}:{limit}"
        cached_raw = self.cache.get(cache_key)
        if cached_raw is not None:
            logger.info("Area discovery cache hit for '%s'", cache_key)
            cached_results = [
                WaterBodyDiscoveryResult.model_validate(item) for item in cached_raw
            ]
            return AreaDiscoveryResponse(
                query_location=query_location,
                center=center,
                radius_km=radius_km,
                bounding_box=bbox,
                total_discovered=len(cached_results),
                results=cached_results,
            )

        # 2. Query provider
        logger.info(
            "Querying area discovery (%s, %s, radius=%s km) via '%s'",
            latitude, longitude, radius_km, target_provider_name,
        )
        try:
            raw_results = await provider.search_area(
                latitude, longitude, radius_km, limit=limit
            )
        except Exception as exc:
            logger.error("Area discovery failed for (%s, %s): %s", latitude, longitude, exc)
            raise DiscoveryProviderError(
                f"Water-body discovery provider '{target_provider_name}' is temporarily unavailable: {str(exc)}",
                code="DISCOVERY_PROVIDER_UNAVAILABLE",
            )

        # 3. Deduplicate
        deduped = self.deduplicate_results(raw_results)

        # 4. Cache
        cache_data = [item.model_dump() for item in deduped]
        self.cache.set(cache_key, target_provider_name, f"{latitude},{longitude}", cache_data)

        return AreaDiscoveryResponse(
            query_location=query_location,
            center=center,
            radius_km=radius_km,
            bounding_box=bbox,
            total_discovered=len(deduped),
            results=deduped,
        )

    def deduplicate_results(
        self, results: List[WaterBodyDiscoveryResult]
    ) -> List[WaterBodyDiscoveryResult]:
        """
        Removes redundant duplicates within the search result batch based on:
        1. Exact (provider, source_id)
        2. Identical geometry hash
        3. Identical normalized name and near-identical centroid (< 2 km apart)
        """
        unique_list: List[WaterBodyDiscoveryResult] = []
        seen_ids = set()
        seen_geom_hashes = set()

        for item in results:
            key_id = (item.provider, item.source_id)
            if key_id in seen_ids:
                continue

            if item.geometry_hash and item.geometry_hash in seen_geom_hashes:
                continue

            # Check name + proximity against already selected results
            is_proximity_duplicate = False
            norm_name = item.name.strip().lower()
            if item.centroid_lat is not None and item.centroid_lon is not None:
                for existing in unique_list:
                    if existing.name.strip().lower() == norm_name:
                        if existing.centroid_lat is not None and existing.centroid_lon is not None:
                            dist_km = self._haversine_distance(
                                item.centroid_lat,
                                item.centroid_lon,
                                existing.centroid_lat,
                                existing.centroid_lon,
                            )
                            if dist_km < 2.0:  # within 2 km
                                is_proximity_duplicate = True
                                break

            if is_proximity_duplicate:
                continue

            seen_ids.add(key_id)
            if item.geometry_hash:
                seen_geom_hashes.add(item.geometry_hash)
            unique_list.append(item)

        return unique_list

    def _enrich_discovery_geometry(self, result: WaterBodyDiscoveryResult) -> WaterBodyDiscoveryResult:
        """
        Ensures bounding box, centroid, and area are populated from geometry_geojson
        if omitted by the discovery provider payload.
        """
        if result.geometry_geojson and (
            result.min_lat is None
            or result.max_lat is None
            or result.centroid_lat is None
            or result.centroid_lon is None
        ):
            try:
                geom = json.loads(result.geometry_geojson)
                coords: List[List[float]] = []

                def _extract_coords(obj):
                    if isinstance(obj, list):
                        if (
                            len(obj) == 2
                            and isinstance(obj[0], (int, float))
                            and isinstance(obj[1], (int, float))
                        ):
                            coords.append(obj)
                        else:
                            for sub in obj:
                                _extract_coords(sub)

                _extract_coords(geom.get("coordinates", []))
                if coords:
                    lons = [c[0] for c in coords]
                    lats = [c[1] for c in coords]
                    min_lon, max_lon = min(lons), max(lons)
                    min_lat, max_lat = min(lats), max(lats)

                    if result.min_lat is None:
                        result.min_lat = round(min_lat, 6)
                    if result.max_lat is None:
                        result.max_lat = round(max_lat, 6)
                    if result.min_lon is None:
                        result.min_lon = round(min_lon, 6)
                    if result.max_lon is None:
                        result.max_lon = round(max_lon, 6)
                    if result.centroid_lat is None:
                        result.centroid_lat = round((min_lat + max_lat) / 2.0, 6)
                    if result.centroid_lon is None:
                        result.centroid_lon = round((min_lon + max_lon) / 2.0, 6)
                    if result.area_sq_km is None:
                        d_lat = abs(max_lat - min_lat) * 111.0
                        mid_lat = (min_lat + max_lat) / 2.0
                        d_lon = abs(max_lon - min_lon) * 111.0 * math.cos(math.radians(mid_lat))
                        result.area_sq_km = round(d_lat * d_lon, 4)
            except Exception as exc:
                logger.debug("Could not derive geometry coordinates from GeoJSON: %s", exc)

        # Fallback bounds from centroid or vice versa
        if result.min_lat is None and result.centroid_lat is not None:
            result.min_lat = result.max_lat = result.centroid_lat
        if result.min_lon is None and result.centroid_lon is not None:
            result.min_lon = result.max_lon = result.centroid_lon
        if result.centroid_lat is None and result.min_lat is not None and result.max_lat is not None:
            result.centroid_lat = round((result.min_lat + result.max_lat) / 2.0, 6)
        if result.centroid_lon is None and result.min_lon is not None and result.max_lon is not None:
            result.centroid_lon = round((result.min_lon + result.max_lon) / 2.0, 6)

        return result

    def import_water_body_with_status(
        self, result: WaterBodyDiscoveryResult
    ) -> Tuple[WaterBody, bool]:
        """
        Converts a validated WaterBodyDiscoveryResult into a stored WaterBody.
        Guarantees idempotency: returns existing record if already imported.
        Returns: (water_body, is_newly_created)
        """
        result = self._enrich_discovery_geometry(result)

        # Signal 1: Check existing by (source, source_id)
        if result.source_id:
            existing = self.repo.get_by_source_and_source_id(result.provider, result.source_id)
            if existing:
                logger.info(
                    "WaterBody already exists for source %s/%s (%s)",
                    result.provider,
                    result.source_id,
                    existing.id,
                )
                return existing, False

        # Signal 2: Check existing by geometry hash
        if result.geometry_hash:
            stmt = select(WaterBody).where(WaterBody.geometry_hash == result.geometry_hash)
            existing_by_hash = self.db.execute(stmt).scalar_one_or_none()
            if existing_by_hash:
                logger.info(
                    "WaterBody with identical geometry hash already exists (%s)",
                    existing_by_hash.id,
                )
                return existing_by_hash, False

        # Signal 3: Check by normalized name and close proximity centroid (< 2km)
        norm_name = result.name.strip().lower()
        if result.centroid_lat is not None and result.centroid_lon is not None:
            candidates = list(
                self.db.execute(
                    select(WaterBody).where(WaterBody.normalized_name == norm_name)
                ).scalars().all()
            )
            for c in candidates:
                if c.centroid_lat is not None and c.centroid_lon is not None:
                    dist_km = self._haversine_distance(
                        result.centroid_lat,
                        result.centroid_lon,
                        c.centroid_lat,
                        c.centroid_lon,
                    )
                    if dist_km < 2.0:
                        logger.info(
                            "WaterBody '%s' matches existing body within %.2f km (%s)",
                            norm_name,
                            dist_km,
                            c.id,
                        )
                        return c, False

        # Create new record
        dto = WaterBodyCreate(
            name=result.name,
            country=result.country,
            state_province=result.state_province,
            district=result.district,
            city=result.city,
            source=result.provider,
            source_id=result.source_id,
            water_body_type=result.water_body_type,
            description=result.description,
            geometry_geojson=result.geometry_geojson,
            min_lat=result.min_lat,
            min_lon=result.min_lon,
            max_lat=result.max_lat,
            max_lon=result.max_lon,
            centroid_lat=result.centroid_lat,
            centroid_lon=result.centroid_lon,
            area_sq_km=result.area_sq_km,
            is_active=True,
        )
        created_wb = self.repo.create(dto)
        return created_wb, True

    def import_water_body(self, result: WaterBodyDiscoveryResult) -> WaterBody:
        """
        Converts a validated WaterBodyDiscoveryResult into a stored WaterBody.
        Guarantees idempotency: returns existing record if already imported.
        """
        wb, _ = self.import_water_body_with_status(result)
        return wb

    def import_water_bodies_batch(
        self, payload: BatchImportRequest
    ) -> BatchImportResponse:
        """
        Imports multiple discovered water bodies in a single request.
        Reports counts of newly imported, already existing, and failed items.
        Idempotent and isolated from satellite acquisition.
        """
        results: List[BatchImportItemResult] = []
        imported_count = 0
        already_existed_count = 0
        failed_count = 0

        for item in payload.water_bodies:
            try:
                wb, created = self.import_water_body_with_status(item)
                status_str = "imported" if created else "already_registered"
                if created:
                    imported_count += 1
                else:
                    already_existed_count += 1

                results.append(
                    BatchImportItemResult(
                        source_id=item.source_id,
                        name=item.name,
                        status=status_str,
                        water_body=WaterBodyRead.model_validate(wb),
                        error=None,
                    )
                )
            except Exception as exc:
                logger.error("Failed to batch-import %s (%s): %s", item.name, item.source_id, exc)
                failed_count += 1
                results.append(
                    BatchImportItemResult(
                        source_id=item.source_id,
                        name=item.name,
                        status="failed",
                        water_body=None,
                        error=str(exc),
                    )
                )

        return BatchImportResponse(
            total_requested=len(payload.water_bodies),
            imported_count=imported_count,
            already_existed_count=already_existed_count,
            failed_count=failed_count,
            results=results,
        )

    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculates distance in kilometers between two lat/lon coordinates."""
        r = 6371.0  # Earth radius in kilometers
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (
            math.sin(d_lat / 2.0) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(d_lon / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return r * c
