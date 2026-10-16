from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient
from datetime import datetime, timezone

from app.schemas.water_body import WaterBodyCreate
from app.services.satellite.models import NormalizedScene, NormalizedAsset


def test_api_satellite_scenes_search_and_acquire(client: TestClient):
    # 1. Create a water body via API
    wb_payload = {
        "name": "Chilika Satellite Test Lake",
        "source": "manual",
        "source_id": "sat-api-test-01",
        "min_lat": 19.46,
        "min_lon": 85.09,
        "max_lat": 19.90,
        "max_lon": 85.65,
        "centroid_lat": 19.68,
        "centroid_lon": 85.25,
        "geometry_geojson": '{"type":"Point","coordinates":[85.25, 19.68]}',
    }
    wb_res = client.post("/api/v1/water-bodies", json=wb_payload)
    assert wb_res.status_code == 201
    wb_id = wb_res.json()["id"]

    # 2. Mock STAC Provider Search
    mock_scene = NormalizedScene(
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2A_T45QTB_20240221_MOCK",
        sensing_start=datetime(2024, 2, 21, 5, 0, 0, tzinfo=timezone.utc),
        cloud_cover_percent=5.2,
        processing_level="L2A",
        bbox=[85.09, 19.46, 85.65, 19.90],
        assets={
            "B02": NormalizedAsset(
                asset_key="B02",
                asset_type="raster_band",
                remote_url="https://example.com/B02.tif",
            ),
            "thumbnail": NormalizedAsset(
                asset_key="thumbnail",
                asset_type="visual",
                remote_url="https://example.com/thumb.jpg",
            ),
        },
    )

    with patch(
        "app.services.satellite.providers.stac.EarthSearchSTACProvider.search_scenes",
        new_callable=AsyncMock,
    ) as mock_search, patch(
        "app.services.satellite.providers.stac.EarthSearchSTACProvider.get_scene",
        new_callable=AsyncMock,
    ) as mock_get_scene, patch(
        "app.services.satellite.providers.stac.EarthSearchSTACProvider.stream_asset_bytes"
    ) as mock_stream:
        mock_search.return_value = [mock_scene]
        mock_get_scene.return_value = mock_scene

        async def fake_stream(url, chunk_size=65536):
            yield b"FAKE_TIFF_BYTES"

        mock_stream.side_effect = fake_stream

        # 3. GET /api/v1/satellite/scenes/search
        search_res = client.get(
            f"/api/v1/satellite/scenes/search?water_body_id={wb_id}&max_cloud_cover=20&limit=5"
        )
        assert search_res.status_code == 200
        data = search_res.json()
        assert data["water_body_id"] == wb_id
        assert len(data["results"]) == 1
        assert data["results"][0]["external_scene_id"] == "S2A_T45QTB_20240221_MOCK"
        assert data["results"][0]["cloud_cover_percent"] == 5.2

        # 4. POST /api/v1/satellite/scenes/{external_scene_id}/acquire
        acquire_res = client.post(
            "/api/v1/satellite/scenes/S2A_T45QTB_20240221_MOCK/acquire",
            json={"assets": ["B02", "thumbnail"]},
        )
        assert acquire_res.status_code == 200
        acq_data = acquire_res.json()
        assert acq_data["status"] == "completed"
        assert acq_data["downloaded_assets"] == 2
        assert acq_data["failed_assets"] == 0
        assert len(acq_data["assets"]) == 2


def test_api_satellite_errors(client: TestClient):
    # Non-existent water body
    res_not_found = client.get("/api/v1/satellite/scenes/search?water_body_id=00000000-0000-0000-0000-000000000000")
    assert res_not_found.status_code == 404
    assert res_not_found.json()["error"]["code"] == "WATER_BODY_NOT_FOUND"

    # Invalid cloud cover > 100
    res_invalid = client.get("/api/v1/satellite/scenes/search?water_body_id=any&max_cloud_cover=150")
    assert res_invalid.status_code == 422
