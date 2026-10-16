from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient
from app.services.discovery.models import WaterBodyDiscoveryResult


def test_api_discovery_providers_list(client: TestClient):
    res = client.get("/api/v1/discovery/providers")
    assert res.status_code == 200
    data = res.json()
    assert "providers" in data
    assert any(p["name"] == "osm" for p in data["providers"])


def test_api_discovery_search_and_import(client: TestClient):
    sample_result = WaterBodyDiscoveryResult(
        provider="osm",
        source_id="relation/555123",
        name="Great Salt Lake",
        water_body_type="lake",
        country="United States",
        state_province="Utah",
        min_lat=40.7,
        min_lon=-113.1,
        max_lat=41.8,
        max_lon=-111.8,
        centroid_lat=41.1,
        centroid_lon=-112.5,
        area_sq_km=4400.0,
        geometry_geojson='{"type":"Polygon","coordinates":[[[-113.1,40.7],[-111.8,40.7],[-111.8,41.8],[-113.1,41.8],[-113.1,40.7]]]}',
    )

    # 1. Mock search call
    with patch(
        "app.services.discovery.providers.osm.OpenStreetMapProvider.search",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = [sample_result]

        # Search endpoint
        res = client.get("/api/v1/discovery/water-bodies/search?q=Great Salt Lake&limit=5")
        assert res.status_code == 200
        search_data = res.json()
        assert search_data["query"] == "Great Salt Lake"
        assert search_data["provider"] == "osm"
        assert len(search_data["results"]) == 1
        assert search_data["results"][0]["name"] == "Great Salt Lake"
        assert search_data["results"][0]["centroid_lat"] == 41.1

    # 2. Import endpoint
    res_import = client.post(
        "/api/v1/discovery/water-bodies/import",
        json=sample_result.model_dump(),
    )
    assert res_import.status_code == 201
    imported_data = res_import.json()
    assert imported_data["name"] == "Great Salt Lake"
    assert imported_data["source"] == "osm"
    assert imported_data["source_id"] == "relation/555123"
    assert imported_data["id"] is not None

    # 3. Verify it shows up in standard /api/v1/water-bodies
    res_list = client.get("/api/v1/water-bodies?search=Great Salt Lake")
    assert res_list.status_code == 200
    assert any(wb["name"] == "Great Salt Lake" for wb in res_list.json()["items"])

    # 4. Duplicate import returns existing entity idempotently
    res_reimport = client.post(
        "/api/v1/discovery/water-bodies/import",
        json=sample_result.model_dump(),
    )
    assert res_reimport.status_code == 201
    assert res_reimport.json()["id"] == imported_data["id"]


def test_api_discovery_validation(client: TestClient):
    # Missing 'q' query parameter
    res = client.get("/api/v1/discovery/water-bodies/search")
    assert res.status_code == 422

    # Unknown provider
    res_bad_prov = client.get("/api/v1/discovery/water-bodies/search?q=test&provider=invalid_prov")
    assert res_bad_prov.status_code == 502
    assert res_bad_prov.json()["error"]["code"] == "UNKNOWN_PROVIDER"
