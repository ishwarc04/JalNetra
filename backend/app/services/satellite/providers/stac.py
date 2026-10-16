import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional
import httpx

from app.core.config import settings
from app.services.satellite.base import SatelliteProvider
from app.services.satellite.models import NormalizedScene, NormalizedAsset

logger = logging.getLogger("jalnetra.satellite.stac")

# Canonical asset key mapping (Earth Search uses lowercase band names or Bxx keys)
CANONICAL_BAND_MAPPING = {
    # Blue, Green, Red, NIR, SWIR1, SWIR2, Scene Classification Layer
    "blue": "B02",
    "green": "B03",
    "red": "B04",
    "rededge1": "B05",
    "rededge2": "B06",
    "rededge3": "B07",
    "nir": "B08",
    "nir08": "B8A",
    "swir16": "B11",
    "swir22": "B12",
    "scl": "SCL",
    "visual": "visual",
    "thumbnail": "thumbnail",
    "preview": "preview",
    # Direct band names
    "b01": "B01",
    "b02": "B02",
    "b03": "B03",
    "b04": "B04",
    "b05": "B05",
    "b06": "B06",
    "b07": "B07",
    "b08": "B08",
    "b8a": "B8A",
    "b09": "B09",
    "b11": "B11",
    "b12": "B12",
}


class EarthSearchSTACProvider(SatelliteProvider):
    """
    STAC Provider querying Element84 Earth Search AWS Sentinel-2 L2A archive.
    Access is completely open over public HTTP, requiring zero AWS credentials.
    """

    def __init__(
        self,
        stac_url: Optional[str] = None,
        collection: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self._stac_url = (stac_url or settings.SATELLITE_STAC_URL).rstrip("/")
        self._collection = collection or settings.SATELLITE_COLLECTION
        self._timeout = timeout_seconds or settings.SATELLITE_REQUEST_TIMEOUT_SECONDS
        self._client = client

    @property
    def name(self) -> str:
        return "earth_search"

    @property
    def collection(self) -> str:
        return self._collection

    async def search_scenes(
        self,
        geometry: Optional[Dict] = None,
        bbox: Optional[List[float]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        max_cloud_cover: float = 30.0,
        limit: int = 10,
    ) -> List[NormalizedScene]:
        search_endpoint = f"{self._stac_url}/search"
        limit = min(max(1, limit), 50)

        # Build datetime range: ISO8601 strings
        datetime_param = None
        if start_date or end_date:
            s_str = start_date.strftime("%Y-%m-%dT%H:%M:%SZ") if start_date else "2015-01-01T00:00:00Z"
            e_str = end_date.strftime("%Y-%m-%dT%H:%M:%SZ") if end_date else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            datetime_param = f"{s_str}/{e_str}"

        # Collections list (search primary collection, and fallback to legacy l2a if applicable)
        collections = [self._collection]
        if self._collection == "sentinel-2-c1-l2a":
            collections.append("sentinel-2-l2a")

        body: Dict[str, Any] = {
            "collections": collections,
            "limit": limit,
            "query": {
                "eo:cloud_cover": {"lte": max_cloud_cover}
            },
        }

        if datetime_param:
            body["datetime"] = datetime_param

        # Spatial constraint: prefer Polygon/MultiPolygon geometry, fallback to bbox
        if geometry and geometry.get("type") in ("Polygon", "MultiPolygon", "Point"):
            body["intersects"] = geometry
        elif bbox and len(bbox) == 4:
            body["bbox"] = bbox
        else:
            raise ValueError("Either valid geometry or 4-element bbox is required for STAC search")

        headers = {
            "User-Agent": settings.WATERBODY_DISCOVERY_USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/geo+json, application/json",
        }

        # Perform bounded HTTP search
        data = await self._send_request("POST", search_endpoint, json_body=body, headers=headers)
        features = data.get("features", [])

        normalized_scenes: List[NormalizedScene] = []
        for feature in features:
            scene = self._normalize_stac_item(feature)
            if scene:
                normalized_scenes.append(scene)

        return normalized_scenes

    async def get_scene(self, external_scene_id: str) -> Optional[NormalizedScene]:
        item_endpoint = f"{self._stac_url}/collections/{self._collection}/items/{external_scene_id}"
        headers = {
            "User-Agent": settings.WATERBODY_DISCOVERY_USER_AGENT,
            "Accept": "application/geo+json, application/json",
        }
        try:
            data = await self._send_request("GET", item_endpoint, headers=headers)
            return self._normalize_stac_item(data)
        except Exception:
            return None

    async def stream_asset_bytes(
        self,
        remote_url: str,
        chunk_size: int = 65536,
    ) -> AsyncGenerator[bytes, None]:
        headers = {"User-Agent": settings.WATERBODY_DISCOVERY_USER_AGENT}

        if self._client:
            async with self._client.stream("GET", remote_url, headers=headers, timeout=self._timeout) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size=chunk_size):
                    yield chunk
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("GET", remote_url, headers=headers) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes(chunk_size=chunk_size):
                        yield chunk

    async def _send_request(
        self,
        method: str,
        url: str,
        json_body: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        retries: int = 3,
    ) -> Dict[str, Any]:
        """Performs HTTP request with exponential backoff on transient errors."""
        last_error = None
        for attempt in range(retries):
            try:
                if self._client:
                    resp = await self._client.request(
                        method, url, json=json_body, headers=headers, timeout=self._timeout
                    )
                else:
                    async with httpx.AsyncClient(timeout=self._timeout) as client:
                        resp = await client.request(
                            method, url, json=json_body, headers=headers
                        )

                if resp.status_code == 404:
                    raise ValueError(f"Resource not found at {url}")

                resp.raise_for_status()
                return resp.json()

            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt < retries - 1:
                    wait_time = 0.5 * (2 ** attempt)
                    logger.warning("Transient error on %s (attempt %d/%d): %s. Retrying in %.1fs...", url, attempt + 1, retries, exc, wait_time)
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("All %d retries failed for %s: %s", retries, url, exc)
                    raise last_error
        raise last_error or RuntimeError("Request failed")

    def _normalize_stac_item(self, item: Dict[str, Any]) -> Optional[NormalizedScene]:
        try:
            external_scene_id = item.get("id")
            if not external_scene_id:
                return None

            properties = item.get("properties", {}) or {}
            dt_str = properties.get("datetime") or properties.get("start_datetime")
            sensing_start = (
                datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                if dt_str
                else datetime.now(timezone.utc)
            )

            end_str = properties.get("end_datetime")
            sensing_end = (
                datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                if end_str
                else None
            )

            cloud_cover = (
                properties.get("eo:cloud_cover")
                if properties.get("eo:cloud_cover") is not None
                else properties.get("cloud_cover")
            )

            product_id = properties.get("sentinel:product_id") or properties.get("product_id") or external_scene_id

            # Parse assets
            raw_assets = item.get("assets", {}) or {}
            normalized_assets: Dict[str, NormalizedAsset] = {}

            for key, val in raw_assets.items():
                if not isinstance(val, dict):
                    continue
                remote_url = val.get("href")
                if not remote_url:
                    continue

                clean_key = key.lower()
                canonical_key = CANONICAL_BAND_MAPPING.get(clean_key, key.upper())

                # Determine asset type
                roles = val.get("roles") or []
                if isinstance(roles, str):
                    roles = [roles]
                asset_type = "raster_band"
                if "overview" in roles or "thumbnail" in roles or canonical_key in ("thumbnail", "preview", "visual"):
                    asset_type = "visual"
                elif "metadata" in roles:
                    asset_type = "metadata"
                elif canonical_key == "SCL":
                    asset_type = "mask"

                normalized_assets[canonical_key] = NormalizedAsset(
                    asset_key=canonical_key,
                    asset_type=asset_type,
                    remote_url=remote_url,
                    mime_type=val.get("type"),
                    file_size_bytes=val.get("file:size"),
                    metadata={
                        "raw_key": key,
                        "title": val.get("title"),
                        "roles": roles,
                    },
                )

            return NormalizedScene(
                provider="earth_search",
                collection=item.get("collection") or self._collection,
                external_scene_id=external_scene_id,
                product_id=product_id,
                sensing_start=sensing_start,
                sensing_end=sensing_end,
                cloud_cover_percent=float(cloud_cover) if cloud_cover is not None else None,
                processing_level=properties.get("processing:level", "L2A"),
                bbox=item.get("bbox"),
                footprint_geojson=item.get("geometry"),
                assets=normalized_assets,
                metadata_json=json.dumps(properties),
            )
        except Exception as exc:
            logger.warning("Failed to normalize STAC item %s: %s", item.get("id"), exc)
            return None
