from starlette.testclient import TestClient


def test_api_water_body_crud_flow(client: TestClient):
    # 1. CREATE
    payload = {
        "name": "Dal Lake",
        "country": "India",
        "state_province": "Jammu & Kashmir",
        "district": "Srinagar",
        "city": "Srinagar",
        "source": "manual",
        "source_id": "dal-001",
        "water_body_type": "lake",
        "min_lat": 34.08,
        "min_lon": 74.83,
        "max_lat": 34.14,
        "max_lon": 74.89,
        "centroid_lat": 34.11,
        "centroid_lon": 74.86,
        "area_sq_km": 18.0,
        "geometry_geojson": '{"type":"Point","coordinates":[74.86,34.11]}',
    }
    res_create = client.post("/api/v1/water-bodies", json=payload)
    assert res_create.status_code == 201
    created_data = res_create.json()
    wb_id = created_data["id"]
    assert created_data["name"] == "Dal Lake"
    assert created_data["normalized_name"] == "dal lake"
    assert created_data["is_active"] is True
    assert created_data["geometry_hash"] is not None

    # 2. GET by ID
    res_get = client.get(f"/api/v1/water-bodies/{wb_id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == wb_id

    # 3. LIST with search & filters
    res_list = client.get("/api/v1/water-bodies?search=Dal&country=India")
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert list_data["total"] >= 1
    assert any(item["id"] == wb_id for item in list_data["items"])

    # 4. UPDATE
    res_update = client.patch(
        f"/api/v1/water-bodies/{wb_id}",
        json={"description": "Urban lake in Srinagar, Kashmir"},
    )
    assert res_update.status_code == 200
    assert res_update.json()["description"] == "Urban lake in Srinagar, Kashmir"

    # 5. DEACTIVATE (Soft delete)
    res_delete = client.delete(f"/api/v1/water-bodies/{wb_id}")
    assert res_delete.status_code == 200
    assert res_delete.json()["is_active"] is False

    # Check deactivated in list with is_active filter
    res_inactive = client.get("/api/v1/water-bodies?is_active=false")
    assert any(item["id"] == wb_id for item in res_inactive.json()["items"])


def test_api_water_body_conflict(client: TestClient):
    payload = {
        "name": "Wular Lake",
        "source": "official_survey",
        "source_id": "wular-99",
    }
    res1 = client.post("/api/v1/water-bodies", json=payload)
    assert res1.status_code == 201

    # Attempting to post same source and source_id returns 409
    res2 = client.post("/api/v1/water-bodies", json=payload)
    assert res2.status_code == 409
    err = res2.json()
    assert err["error"]["code"] == "CONFLICT"


def test_api_water_body_validation_errors(client: TestClient):
    # Invalid empty name
    res = client.post("/api/v1/water-bodies", json={"name": "   "})
    assert res.status_code == 422

    # Invalid latitude out of range
    res = client.post(
        "/api/v1/water-bodies",
        json={"name": "Test Lake", "min_lat": 95.0},
    )
    assert res.status_code == 422

    # Inverted bounding box min_lat > max_lat
    res = client.post(
        "/api/v1/water-bodies",
        json={"name": "Test Lake", "min_lat": 30.0, "max_lat": 10.0},
    )
    assert res.status_code == 422


def test_api_storage_status(client: TestClient):
    res = client.get("/api/v1/storage/status")
    assert res.status_code == 200
    data = res.json()
    assert "database" in data
    assert data["database"]["status"] == "ok"
    assert "directories" in data
    assert data["directories"]["data"] == "ok"
    assert data["directories"]["scenes"] == "ok"
    assert data["directories"]["processed"] == "ok"
    assert data["directories"]["cache"] == "ok"
