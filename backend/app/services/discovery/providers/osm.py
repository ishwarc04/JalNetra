import json
import logging
import math
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import settings
from app.services.discovery.base import WaterBodyProvider
from app.services.discovery.models import (
    WaterBodyDiscoveryResult,
    GeocodedLocation,
    compute_geometry_hash_from_dict,
)

logger = logging.getLogger("jalnetra.discovery.osm")

# Canonical water body categories and keywords in OpenStreetMap
WATER_BODY_KEYWORDS = {
    "water",
    "lake",
    "reservoir",
    "river",
    "stream",
    "canal",
    "lagoon",
    "pond",
    "wetland",
    "basin",
    "bay",
    "strait",
    "oxbow",
}

WATER_CLASSES = {"natural", "waterway", "landuse"}


class OpenStreetMapProvider(WaterBodyProvider):
    """
    OpenStreetMap provider leveraging the public Nominatim API with polygon GeoJSON output.
    Follows OSM Nominatim Usage Policy:
    - Custom descriptive User-Agent with contact/app identity
    - Strict query timeouts
    - Structured query parameters
    """

    NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

    def __init__(
        self,
        user_agent: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        base_url: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._user_agent = user_agent or settings.WATERBODY_DISCOVERY_USER_AGENT
        self._timeout = timeout_seconds or settings.WATERBODY_DISCOVERY_TIMEOUT_SECONDS
        self._base_url = base_url or self.NOMINATIM_URL
        self._client = client

    @property
    def name(self) -> str:
        return "osm"

    @property
    def description(self) -> str:
        return "OpenStreetMap Nominatim Geographic Search Engine"

    async def check_health(self) -> bool:
        # Static availability check based on configuration
        return settings.WATERBODY_DISCOVERY_ENABLED

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> List[WaterBodyDiscoveryResult]:
        query = query.strip()
        if not query:
            return []

        limit = min(max(1, limit), 20)

        params: Dict[str, Any] = {
            "q": query,
            "format": "jsonv2",
            "polygon_geojson": 1,
            "addressdetails": 1,
            "extratags": 1,
            "limit": limit,
        }

        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }

        try:
            if self._client:
                response = await self._client.get(
                    self._base_url,
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(
                        self._base_url,
                        params=params,
                        headers=headers,
                    )

            if response.status_code >= 400:
                logger.warning(
                    "OSM Nominatim returned HTTP %s for query '%s'",
                    response.status_code,
                    query,
                )
                return []

            data = response.json()
            if not isinstance(data, list):
                logger.warning("OSM Nominatim unexpected response format: %s", type(data))
                return []

            results: List[WaterBodyDiscoveryResult] = []
            for item in data:
                normalized = self._normalize_item(item)
                if normalized:
                    results.append(normalized)

            # Sort/prioritize actual water body types over generic geographic places
            results.sort(key=lambda r: (0 if self._is_water_feature(r) else 1))
            return results

        except httpx.TimeoutException:
            logger.warning("OSM Nominatim timeout after %ss for query '%s'", self._timeout, query)
            raise
        except httpx.RequestError as exc:
            logger.warning("OSM Nominatim network error: %s", exc)
            raise
        except Exception as exc:
            logger.error("OSM Nominatim unexpected exception: %s", exc, exc_info=True)
            raise

    def _is_water_feature(self, res: WaterBodyDiscoveryResult) -> bool:
        wb_type = (res.water_body_type or "").lower()
        if any(kw in wb_type for kw in WATER_BODY_KEYWORDS):
            return True
        name_lower = res.name.lower()
        if any(kw in name_lower for kw in WATER_BODY_KEYWORDS):
            return True
        return False

    def _normalize_item(self, item: Dict[str, Any]) -> Optional[WaterBodyDiscoveryResult]:
        try:
            osm_type = item.get("osm_type", "node")
            osm_id = item.get("osm_id", "")
            source_id = f"{osm_type}/{osm_id}" if osm_id else str(item.get("place_id", ""))

            # Name extraction
            name = item.get("name")
            display_name = item.get("display_name", "")
            if not name:
                name = display_name.split(",")[0].strip() if display_name else "Unknown Water Body"

            # Classification & water body type
            item_class = str(item.get("class", "")).lower()
            item_type = str(item.get("type", "")).lower()

            # Determine water body type
            water_body_type = None
            if item_type in WATER_BODY_KEYWORDS:
                water_body_type = item_type
            elif item_class in WATER_CLASSES and item_type:
                water_body_type = item_type
            elif any(kw in (name.lower()) for kw in WATER_BODY_KEYWORDS):
                for kw in WATER_BODY_KEYWORDS:
                    if kw in name.lower():
                        water_body_type = kw
                        break
            else:
                water_body_type = item_type or item_class or "water"

            # Address details
            address = item.get("address", {}) or {}
            country = address.get("country")
            state_province = address.get("state") or address.get("province") or address.get("region")
            district = address.get("state_district") or address.get("county") or address.get("district")
            city = address.get("city") or address.get("town") or address.get("municipality") or address.get("village")

            # Geometry parsing
            geom = item.get("geojson")
            geom_str = None
            geom_hash = None
            if geom and isinstance(geom, dict):
                geom_type = geom.get("type")
                if geom_type in ("Point", "Polygon", "MultiPolygon", "LineString", "MultiLineString"):
                    geom_str = json.dumps(geom)
                    geom_hash = compute_geometry_hash_from_dict(geom)

            # Bounding box [min_lat, max_lat, min_lon, max_lon] in Nominatim
            min_lat, max_lat, min_lon, max_lon = None, None, None, None
            bbox_raw = item.get("boundingbox")
            if bbox_raw and len(bbox_raw) == 4:
                try:
                    min_lat = float(bbox_raw[0])
                    max_lat = float(bbox_raw[1])
                    min_lon = float(bbox_raw[2])
                    max_lon = float(bbox_raw[3])
                except (ValueError, TypeError):
                    pass

            # Centroid
            centroid_lat, centroid_lon = None, None
            try:
                if "lat" in item and "lon" in item:
                    centroid_lat = float(item["lat"])
                    centroid_lon = float(item["lon"])
            except (ValueError, TypeError):
                pass

            # Calculate fallback bounds or centroid from each other if missing
            if centroid_lat is None and min_lat is not None and max_lat is not None:
                centroid_lat = (min_lat + max_lat) / 2.0
            if centroid_lon is None and min_lon is not None and max_lon is not None:
                centroid_lon = (min_lon + max_lon) / 2.0

            if min_lat is None and centroid_lat is not None:
                min_lat = max_lat = centroid_lat
            if min_lon is None and centroid_lon is not None:
                min_lon = max_lon = centroid_lon

            # Estimate approximate area in sq km if polygon bounding box is available
            area_sq_km = None
            if min_lat is not None and max_lat is not None and min_lon is not None and max_lon is not None:
                d_lat = abs(max_lat - min_lat)
                d_lon = abs(max_lon - min_lon)
                if d_lat > 0 or d_lon > 0:
                    # Rough rectangular approximation at latitude: 1 deg lat ≈ 111 km, 1 deg lon ≈ 111 * cos(lat)
                    avg_lat_rad = math.radians(centroid_lat if centroid_lat is not None else min_lat)
                    km_lat = d_lat * 111.0
                    km_lon = d_lon * 111.0 * math.cos(avg_lat_rad)
                    area_sq_km = round(km_lat * km_lon, 3)

            return WaterBodyDiscoveryResult(
                provider="osm",
                source_id=source_id,
                name=name,
                water_body_type=water_body_type,
                country=country,
                state_province=state_province,
                district=district,
                city=city,
                description=display_name,
                geometry_geojson=geom_str,
                geometry_hash=geom_hash,
                min_lat=min_lat,
                min_lon=min_lon,
                max_lat=max_lat,
                max_lon=max_lon,
                centroid_lat=centroid_lat,
                centroid_lon=centroid_lon,
                area_sq_km=area_sq_km,
                source_metadata={
                    "osm_type": osm_type,
                    "osm_id": osm_id,
                    "place_id": item.get("place_id"),
                    "class": item_class,
                    "type": item_type,
                    "importance": item.get("importance"),
                },
            )
        except Exception as exc:
            logger.warning("Failed to normalize OSM item %s: %s", item.get("place_id"), exc)
            return None

    async def geocode_location(
        self,
        query: str,
        limit: int = 5,
    ) -> List[GeocodedLocation]:
        query = query.strip()
        if not query:
            return []

        limit = min(max(1, limit), 10)
        params: Dict[str, Any] = {
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": limit,
        }
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }

        try:
            if self._client:
                response = await self._client.get(
                    self._base_url,
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(
                        self._base_url,
                        params=params,
                        headers=headers,
                    )

            if response.status_code >= 400:
                logger.warning("Geocoding returned HTTP %s for '%s'", response.status_code, query)
                return []

            data = response.json()
            if not isinstance(data, list):
                return []

            results: List[GeocodedLocation] = []
            for item in data:
                try:
                    lat = float(item["lat"])
                    lon = float(item["lon"])
                    display_name = item.get("display_name", query)
                    item_type = item.get("type") or item.get("category")
                    bbox_raw = item.get("boundingbox")
                    bbox = None
                    if bbox_raw and len(bbox_raw) == 4:
                        bbox = [float(b) for b in bbox_raw]

                    results.append(
                        GeocodedLocation(
                            display_name=display_name,
                            latitude=lat,
                            longitude=lon,
                            type=item_type,
                            boundingbox=bbox,
                        )
                    )
                except (ValueError, KeyError, TypeError):
                    continue

            return results
        except httpx.TimeoutException:
            logger.warning("Geocoding timeout after %ss for query '%s'", self._timeout, query)
            raise
        except httpx.RequestError as exc:
            logger.warning("Geocoding network error for '%s': %s", query, exc)
            raise

    async def search_area(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        limit: int = 30,
    ) -> List[WaterBodyDiscoveryResult]:
        radius_meters = int(max(100, radius_km * 1000))
        limit = min(max(1, limit), 60)

        ql = f"""[out:json][timeout:25];
(
  nwr["natural"="water"](around:{radius_meters},{latitude},{longitude});
  nwr["water"](around:{radius_meters},{latitude},{longitude});
  nwr["waterway"~"^(riverbank|dock)$"](around:{radius_meters},{latitude},{longitude});
  nwr["landuse"~"^(reservoir|basin)$"](around:{radius_meters},{latitude},{longitude});
);
out geom {limit};"""

        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }

        overpass_endpoints = [
            "https://overpass-api.de/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        ]

        for ep in overpass_endpoints:
            try:
                if self._client:
                    resp = await self._client.post(
                        ep,
                        data={"data": ql},
                        headers=headers,
                        timeout=self._timeout,
                    )
                else:
                    async with httpx.AsyncClient(timeout=self._timeout) as client:
                        resp = await client.post(
                            ep,
                            data={"data": ql},
                            headers=headers,
                        )

                if resp.status_code == 200:
                    data = resp.json()
                    elements = data.get("elements", [])
                    results: List[WaterBodyDiscoveryResult] = []
                    for el in elements:
                        normalized = self._normalize_overpass_element(el)
                        if normalized:
                            results.append(normalized)

                    # Prioritize named water bodies over unnamed
                    results.sort(key=lambda r: (1 if r.name.startswith("Unnamed") else 0))
                    return results[:limit]
            except Exception as err:
                logger.warning("Overpass endpoint %s failed for area query: %s", ep, err)
                continue

        # Fallback to bounded Nominatim search if Overpass instances fail
        logger.info("Falling back to Nominatim bounded search for (%s, %s, %s km)", latitude, longitude, radius_km)
        return await self._search_area_nominatim_fallback(latitude, longitude, radius_km, limit)

    def _normalize_overpass_element(self, el: Dict[str, Any]) -> Optional[WaterBodyDiscoveryResult]:
        try:
            osm_type = el.get("type", "way")
            osm_id = el.get("id", "")
            source_id = f"{osm_type}/{osm_id}"
            tags = el.get("tags", {}) or {}

            # Name extraction
            name = tags.get("name") or tags.get("name:en") or tags.get("alt_name")
            water_body_type = (
                tags.get("water")
                or tags.get("natural")
                or tags.get("waterway")
                or tags.get("landuse")
                or "water"
            )

            if not name:
                name = f"Unnamed {water_body_type.capitalize()} ({source_id})"

            geom_dict = None
            points = el.get("geometry", [])
            min_lat, max_lat, min_lon, max_lon = None, None, None, None
            centroid_lat, centroid_lon = None, None

            if points:
                lats = [pt["lat"] for pt in points if "lat" in pt]
                lons = [pt["lon"] for pt in points if "lon" in pt]
                if lats and lons:
                    min_lat, max_lat = min(lats), max(lats)
                    min_lon, max_lon = min(lons), max(lons)
                    centroid_lat = sum(lats) / len(lats)
                    centroid_lon = sum(lons) / len(lons)

                coords = [[pt["lon"], pt["lat"]] for pt in points if "lat" in pt and "lon" in pt]
                if len(coords) >= 3:
                    if coords[0] == coords[-1]:
                        geom_dict = {"type": "Polygon", "coordinates": [coords]}
                    elif len(coords) >= 4:
                        geom_dict = {"type": "Polygon", "coordinates": [coords + [coords[0]]]}
                    else:
                        geom_dict = {"type": "LineString", "coordinates": coords}
                elif coords:
                    geom_dict = {"type": "LineString", "coordinates": coords}
            elif "lat" in el and "lon" in el:
                centroid_lat = float(el["lat"])
                centroid_lon = float(el["lon"])
                min_lat = max_lat = centroid_lat
                min_lon = max_lon = centroid_lon
                geom_dict = {"type": "Point", "coordinates": [centroid_lon, centroid_lat]}

            geom_str = json.dumps(geom_dict) if geom_dict else None
            geom_hash = compute_geometry_hash_from_dict(geom_dict) if geom_dict else None

            # Calculate area estimation
            area_sq_km = None
            if min_lat is not None and max_lat is not None and min_lon is not None and max_lon is not None:
                d_lat = abs(max_lat - min_lat)
                d_lon = abs(max_lon - min_lon)
                if d_lat > 0 or d_lon > 0:
                    avg_lat_rad = math.radians(centroid_lat if centroid_lat is not None else min_lat)
                    km_lat = d_lat * 111.0
                    km_lon = d_lon * 111.0 * math.cos(avg_lat_rad)
                    area_sq_km = round(km_lat * km_lon, 3)

            return WaterBodyDiscoveryResult(
                provider="osm",
                source_id=source_id,
                name=name,
                water_body_type=water_body_type,
                country=None,
                state_province=None,
                district=None,
                city=None,
                description=tags.get("description"),
                geometry_geojson=geom_str,
                geometry_hash=geom_hash,
                min_lat=min_lat,
                min_lon=min_lon,
                max_lat=max_lat,
                max_lon=max_lon,
                centroid_lat=centroid_lat,
                centroid_lon=centroid_lon,
                area_sq_km=area_sq_km,
                source_metadata={
                    "osm_type": osm_type,
                    "osm_id": osm_id,
                    "tags": tags,
                },
            )
        except Exception as exc:
            logger.warning("Failed to normalize Overpass element: %s", exc)
            return None

    async def _search_area_nominatim_fallback(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        limit: int,
    ) -> List[WaterBodyDiscoveryResult]:
        d_lat = radius_km / 111.0
        d_lon = radius_km / (111.0 * max(0.01, math.cos(math.radians(latitude))))
        min_lat = latitude - d_lat
        max_lat = latitude + d_lat
        min_lon = longitude - d_lon
        max_lon = longitude + d_lon

        params: Dict[str, Any] = {
            "q": "water",
            "viewbox": f"{min_lon},{max_lat},{max_lon},{min_lat}",
            "bounded": 1,
            "format": "jsonv2",
            "polygon_geojson": 1,
            "addressdetails": 1,
            "limit": limit,
        }
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }

        try:
            if self._client:
                resp = await self._client.get(
                    self._base_url,
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(
                        self._base_url,
                        params=params,
                        headers=headers,
                    )
            if resp.status_code == 200:
                data = resp.json()
                results: List[WaterBodyDiscoveryResult] = []
                if isinstance(data, list):
                    for item in data:
                        normalized = self._normalize_item(item)
                        if normalized:
                            results.append(normalized)
                return results[:limit]
        except Exception as exc:
            logger.warning("Nominatim area fallback failed: %s", exc)
        return []

