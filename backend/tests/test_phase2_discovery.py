import pytest
from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models.water_body import WaterBody
from app.services.discovery.models import (
    GeocodedLocation,
    WaterBodyDiscoveryResult,
)
from app.services.discovery.service import DiscoveryProviderError


# 1. Location search success
def test_location_search_success(client: TestClient):
    mock_locations = [
        GeocodedLocation(
            display_name="Delhi, India",
            latitude=28.6139,
            longitude=77.2090,
            type="administrative",
            boundingbox=[28.4046, 28.8834, 76.8388, 77.3453],
        )
    ]
    with patch(
        "app.services.discovery.providers.osm.OpenStreetMapProvider.geocode_location",
        new_callable=AsyncMock,
    ) as mock_geo:
        mock_geo.return_value = mock_locations

        res = client.get("/api/v1/discovery/location/search?q=Delhi")
        assert res.status_code == 200
        data = res.json()
        assert data["query"] == "Delhi"
        assert len(data["results"]) == 1
        assert data["results"][0]["display_name"] == "Delhi, India"
        assert data["results"][0]["latitude"] == 28.6139
        assert data["results"][0]["longitude"] == 77.2090


# 2. Location search failure / empty
def test_location_search_empty_result(client: TestClient):
    with patch(
        "app.services.discovery.providers.osm.OpenStreetMapProvider.geocode_location",
        new_callable=AsyncMock,
    ) as mock_geo:
        mock_geo.return_value = []

        res = client.get("/api/v1/discovery/location/search?q=NonExistentPlaceXYZ123")
        assert res.status_code == 200
        data = res.json()
        assert data["query"] == "NonExistentPlaceXYZ123"
        assert data["results"] == []


# 3. Invalid location parameter (validation error)
def test_location_search_invalid_params(client: TestClient):
    # Empty query or missing q
    res = client.get("/api/v1/discovery/location/search?q=")
    assert res.status_code == 422

    res_missing = client.get("/api/v1/discovery/location/search")
    assert res_missing.status_code == 422


# 4. Radius validation
def test_area_discovery_radius_validation(client: TestClient):
    # Radius too large (> 50 km)
    res_large = client.get("/api/v1/discovery/water-bodies/area?latitude=28.6&longitude=77.2&radius_km=100.0")
    assert res_large.status_code == 422

    # Radius too small (<= 0)
    res_zero = client.get("/api/v1/discovery/water-bodies/area?latitude=28.6&longitude=77.2&radius_km=0.0")
    assert res_zero.status_code == 422

    # Latitude out of bounds
    res_lat = client.get("/api/v1/discovery/water-bodies/area?latitude=95.0&longitude=77.2&radius_km=5.0")
    assert res_lat.status_code == 422


# 5. Area discovery success
def test_area_discovery_success(client: TestClient):
    sample_wb = WaterBodyDiscoveryResult(
        provider="osm",
        source_id="way/12345",
        name="Hauz Khas Lake",
        water_body_type="lake",
        centroid_lat=28.552,
        centroid_lon=77.195,
        min_lat=28.550,
        max_lat=28.554,
        min_lon=77.193,
        max_lon=77.197,
        area_sq_km=0.15,
        geometry_geojson='{"type":"Polygon","coordinates":[[[77.193,28.550],[77.197,28.550],[77.197,28.554],[77.193,28.554],[77.193,28.550]]]}',
    )

    with patch(
        "app.services.discovery.providers.osm.OpenStreetMapProvider.search_area",
        new_callable=AsyncMock,
    ) as mock_area:
        mock_area.return_value = [sample_wb]

        res = client.get("/api/v1/discovery/water-bodies/area?latitude=28.6139&longitude=77.2090&radius_km=5.0&query_location=Delhi")
        assert res.status_code == 200
        data = res.json()
        assert data["query_location"] == "Delhi"
        assert data["center"]["latitude"] == 28.6139
        assert data["radius_km"] == 5.0
        assert "bounding_box" in data
        assert data["total_discovered"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "Hauz Khas Lake"
        assert data["results"][0]["source_id"] == "way/12345"


# 6. Empty discovery result
def test_area_discovery_empty(client: TestClient):
    with patch(
        "app.services.discovery.providers.osm.OpenStreetMapProvider.search_area",
        new_callable=AsyncMock,
    ) as mock_area:
        mock_area.return_value = []

        res = client.get("/api/v1/discovery/water-bodies/area?latitude=28.0&longitude=77.0&radius_km=1.0")
        assert res.status_code == 200
        data = res.json()
        assert data["total_discovered"] == 0
        assert data["results"] == []


# 7. Provider timeout / error handling
def test_provider_error_handling(client: TestClient):
    with patch(
        "app.services.discovery.providers.osm.OpenStreetMapProvider.search_area",
        new_callable=AsyncMock,
    ) as mock_area:
        mock_area.side_effect = Exception("Connection timed out to Overpass")

        res = client.get("/api/v1/discovery/water-bodies/area?latitude=28.0&longitude=77.0&radius_km=1.0")
        assert res.status_code == 502
        assert "DISCOVERY_PROVIDER_UNAVAILABLE" in res.json()["error"]["code"]


# 8. Water-body normalization in Overpass element parsing
def test_overpass_element_normalization():
    from app.services.discovery.providers.osm import OpenStreetMapProvider
    prov = OpenStreetMapProvider()

    # Closed way with name
    element = {
        "type": "way",
        "id": 999111,
        "tags": {
            "name": "Lakaki Talav",
            "water": "lake",
        },
        "geometry": [
            {"lat": 18.53, "lon": 73.84},
            {"lat": 18.54, "lon": 73.84},
            {"lat": 18.54, "lon": 73.85},
            {"lat": 18.53, "lon": 73.85},
            {"lat": 18.53, "lon": 73.84},
        ],
    }
    normalized = prov._normalize_overpass_element(element)
    assert normalized is not None
    assert normalized.name == "Lakaki Talav"
    assert normalized.source_id == "way/999111"
    assert normalized.water_body_type == "lake"
    assert normalized.geometry_geojson is not None
    assert '"type": "Polygon"' in normalized.geometry_geojson
    assert normalized.centroid_lat is not None


# 9. Successful registration
def test_successful_registration(client: TestClient, db_session: Session):
    wb_payload = WaterBodyDiscoveryResult(
        provider="osm",
        source_id="relation/pune_lake_1",
        name="Peshve Udyan Lake",
        water_body_type="lake",
        country="India",
        centroid_lat=18.50,
        centroid_lon=73.85,
        area_sq_km=0.08,
    )

    res = client.post("/api/v1/discovery/water-bodies/import", json=wb_payload.model_dump())
    assert res.status_code == 201
    created = res.json()
    assert created["name"] == "Peshve Udyan Lake"
    assert created["source_id"] == "relation/pune_lake_1"

    # Verify directly in SQLite database
    db_wb = db_session.execute(
        select(WaterBody).where(WaterBody.source_id == "relation/pune_lake_1")
    ).scalar_one_or_none()
    assert db_wb is not None
    assert db_wb.name == "Peshve Udyan Lake"


# 10. Duplicate registration deduplication (idempotence)
def test_duplicate_registration_deduplication(client: TestClient, db_session: Session):
    wb_payload = WaterBodyDiscoveryResult(
        provider="osm",
        source_id="way/dup_test_01",
        name="Sanjay Lake",
        water_body_type="lake",
        country="India",
        centroid_lat=28.61,
        centroid_lon=77.30,
        area_sq_km=0.17,
    )

    # First registration
    res1 = client.post("/api/v1/discovery/water-bodies/import", json=wb_payload.model_dump())
    assert res1.status_code == 201
    id1 = res1.json()["id"]

    # Second registration of identical source and source_id
    res2 = client.post("/api/v1/discovery/water-bodies/import", json=wb_payload.model_dump())
    assert res2.status_code == 201
    id2 = res2.json()["id"]

    # Must return existing ID without duplicate error or new record
    assert id1 == id2
    count = db_session.execute(
        select(WaterBody).where(WaterBody.source_id == "way/dup_test_01")
    ).scalars().all()
    assert len(count) == 1
