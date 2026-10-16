import json
import pytest
import httpx
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from app.services.discovery.models import (
    WaterBodyDiscoveryResult,
    DiscoverySearchResponse,
    compute_geometry_hash_from_dict,
)
from app.services.discovery.providers.osm import OpenStreetMapProvider
from app.services.discovery.cache import DiscoveryCacheService
from app.services.discovery.service import (
    WaterBodyDiscoveryService,
    DiscoveryProviderError,
)
from app.services.storage_service import LocalStorageService
from app.db.repositories.water_body_repository import WaterBodyRepository


# Sample Mock Responses from Nominatim
MOCK_NOMINATIM_SUCCESS = [
    {
        "place_id": 123456,
        "osm_type": "relation",
        "osm_id": 987654,
        "name": "Chilika Lake",
        "display_name": "Chilika Lake, Puri, Odisha, India",
        "class": "natural",
        "type": "water",
        "importance": 0.75,
        "lat": "19.716",
        "lon": "85.316",
        "boundingbox": ["19.45", "19.90", "85.05", "85.60"],
        "geojson": {
            "type": "Polygon",
            "coordinates": [
                [
                    [85.05, 19.45],
                    [85.60, 19.45],
                    [85.60, 19.90],
                    [85.05, 19.90],
                    [85.05, 19.45],
                ]
            ],
        },
        "address": {
            "natural": "Chilika Lake",
            "county": "Puri",
            "state": "Odisha",
            "country": "India",
            "country_code": "in",
        },
    },
    {
        "place_id": 123457,
        "osm_type": "relation",
        "osm_id": 987655,
        "name": "Chilika Lagoon Nearby",
        "display_name": "Chilika Lagoon Nearby, Puri, Odisha, India",
        "class": "natural",
        "type": "water",
        "importance": 0.5,
        "lat": "19.720",
        "lon": "85.320",
        "boundingbox": ["19.70", "19.74", "85.30", "85.34"],
        "geojson": {"type": "Point", "coordinates": [85.320, 19.720]},
        "address": {"state": "Odisha", "country": "India"},
    },
]


@pytest.mark.anyio
async def test_osm_provider_normalization():
    # Test normalization from raw mock data
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = MOCK_NOMINATIM_SUCCESS
    mock_client.get.return_value = mock_response

    provider = OpenStreetMapProvider(client=mock_client)
    results = await provider.search("Chilika Lake", limit=5)

    assert len(results) == 2
    r1 = results[0]
    assert r1.provider == "osm"
    assert r1.source_id == "relation/987654"
    assert r1.name == "Chilika Lake"
    assert r1.water_body_type == "water"
    assert r1.country == "India"
    assert r1.state_province == "Odisha"
    assert r1.district == "Puri"
    assert r1.min_lat == 19.45
    assert r1.max_lat == 19.90
    assert r1.min_lon == 85.05
    assert r1.max_lon == 85.60
    assert r1.centroid_lat == 19.716
    assert r1.centroid_lon == 85.316
    assert r1.area_sq_km is not None and r1.area_sq_km > 0
    assert r1.geometry_hash is not None
    assert r1.geometry_geojson is not None


@pytest.mark.anyio
async def test_osm_provider_timeout_handling():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = httpx.TimeoutException("Read timed out")

    provider = OpenStreetMapProvider(client=mock_client)
    with pytest.raises(httpx.TimeoutException):
        await provider.search("Timeout Lake")


@pytest.mark.anyio
async def test_osm_provider_malformed_response():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"error": "unexpected structure"}
    mock_client.get.return_value = mock_response

    provider = OpenStreetMapProvider(client=mock_client)
    results = await provider.search("Bad Format")
    assert results == []


def test_geometry_hash_determinism():
    geom1 = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
    }
    # Same geometry, different dictionary key order
    geom2 = {
        "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
        "type": "Polygon",
    }
    h1 = compute_geometry_hash_from_dict(geom1)
    h2 = compute_geometry_hash_from_dict(geom2)
    assert h1 is not None
    assert h1 == h2


def test_discovery_deduplication():
    # Setup test discovery service
    service = WaterBodyDiscoveryService(db=None, providers={})

    r1 = WaterBodyDiscoveryResult(
        provider="osm",
        source_id="rel/1",
        name="Lake Victoria",
        country="Uganda",
        centroid_lat=-1.0,
        centroid_lon=33.0,
        geometry_geojson='{"type":"Point","coordinates":[33.0,-1.0]}',
        geometry_hash="hash-1",
    )
    # Duplicate by exact provider & source_id
    r2 = WaterBodyDiscoveryResult(
        provider="osm",
        source_id="rel/1",
        name="Lake Victoria Duplicate",
        country="Uganda",
    )
    # Duplicate by geometry hash
    r3 = WaterBodyDiscoveryResult(
        provider="osm",
        source_id="rel/2",
        name="Lake Victoria Geometry Dupe",
        geometry_hash="hash-1",
    )
    # Duplicate by normalized name and close centroid (< 2 km away, e.g. 0.005 deg)
    r4 = WaterBodyDiscoveryResult(
        provider="osm",
        source_id="rel/3",
        name="lake victoria",
        centroid_lat=-1.002,
        centroid_lon=33.002,
    )
    # Distinct entity: different location (different lake)
    r5 = WaterBodyDiscoveryResult(
        provider="osm",
        source_id="rel/4",
        name="Lake Victoria",
        centroid_lat=45.0,  # Far away
        centroid_lon=-93.0,
    )

    deduped = service.deduplicate_results([r1, r2, r3, r4, r5])
    assert len(deduped) == 2
    assert deduped[0].source_id == "rel/1"
    assert deduped[1].source_id == "rel/4"


def test_discovery_caching(db_session, tmp_path):
    storage = LocalStorageService(base_dir=tmp_path)
    cache = DiscoveryCacheService(db=db_session, storage=storage, default_ttl_seconds=300)

    key = cache.build_cache_key("osm", "  Lake   Pichola  ", 10)
    assert key == "waterbody-discovery:osm:lake pichola:10"

    # Cache miss
    assert cache.get(key) is None

    # Set cache
    sample_data = [{"name": "Lake Pichola", "country": "India"}]
    cache.set(key, "osm", "lake pichola", sample_data)

    # Cache hit
    retrieved = cache.get(key)
    assert retrieved is not None
    assert len(retrieved) == 1
    assert retrieved[0]["name"] == "Lake Pichola"

    # Expiry test: create expired cache entry directly
    expired_key = cache.build_cache_key("osm", "expired query", 10)
    cache.set(expired_key, "osm", "expired query", sample_data)
    entry = cache.repo.get_by_key(expired_key)
    entry.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    cache.db.commit()

    # Expired entry should return None
    assert cache.get(expired_key) is None


@pytest.mark.anyio
async def test_discovery_service_search_and_import(db_session, tmp_path):
    mock_provider = AsyncMock(spec=OpenStreetMapProvider)
    mock_provider.name = "osm"
    mock_provider.description = "Mock Provider"

    res1 = WaterBodyDiscoveryResult(
        provider="osm",
        source_id="rel/888",
        name="Dal Lake",
        water_body_type="lake",
        country="India",
        state_province="Jammu and Kashmir",
        centroid_lat=34.11,
        centroid_lon=74.86,
        min_lat=34.08,
        min_lon=74.83,
        max_lat=34.14,
        max_lon=74.89,
        area_sq_km=18.0,
        geometry_geojson='{"type":"Point","coordinates":[74.86,34.11]}',
    )
    mock_provider.search.return_value = [res1]

    storage = LocalStorageService(base_dir=tmp_path)
    service = WaterBodyDiscoveryService(
        db=db_session,
        providers={"osm": mock_provider},
    )
    service.cache = DiscoveryCacheService(db=db_session, storage=storage)

    # 1. Search
    response = await service.search(query="Dal Lake", limit=5)
    assert response.query == "Dal Lake"
    assert len(response.results) == 1
    assert response.results[0].name == "Dal Lake"
    mock_provider.search.assert_called_once()

    # 2. Second search should hit cache (mock_provider not called again)
    mock_provider.search.reset_mock()
    cached_resp = await service.search(query="Dal Lake", limit=5)
    assert len(cached_resp.results) == 1
    assert mock_provider.search.call_count == 0

    # 3. Import
    imported = service.import_water_body(res1)
    assert imported.id is not None
    assert imported.name == "Dal Lake"
    assert imported.source == "osm"
    assert imported.source_id == "rel/888"

    # 4. Duplicate Import should be idempotent and return same record
    second_import = service.import_water_body(res1)
    assert second_import.id == imported.id


@pytest.mark.anyio
async def test_discovery_service_provider_failure(db_session):
    mock_provider = AsyncMock(spec=OpenStreetMapProvider)
    mock_provider.name = "osm"
    mock_provider.description = "Mock Provider"
    mock_provider.search.side_effect = httpx.ConnectError("Service down")

    service = WaterBodyDiscoveryService(
        db=db_session,
        providers={"osm": mock_provider},
    )

    with pytest.raises(DiscoveryProviderError) as exc_info:
        await service.search("Failing Lake")
    assert exc_info.value.code == "DISCOVERY_PROVIDER_UNAVAILABLE"
