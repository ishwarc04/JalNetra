import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.db.models.water_body import WaterBody
from app.db.models.satellite_observation import SatelliteObservation
from app.services.satellite.models import NormalizedScene, NormalizedAsset


def _create_test_water_body(db_session: Session, name="Chilika Lake Test") -> WaterBody:
    wb = WaterBody(
        name=name,
        normalized_name=name.lower(),
        country="India",
        source="osm",
        source_id=f"way/{name.replace(' ', '_').lower()}",
        water_body_type="lake",
        min_lat=19.5,
        min_lon=85.3,
        max_lat=19.7,
        max_lon=85.5,
        centroid_lat=19.6,
        centroid_lon=85.4,
        area_sq_km=82.5,
    )
    db_session.add(wb)
    db_session.commit()
    db_session.refresh(wb)
    return wb


def _make_mock_scene(external_id: str, date_str: str, cloud_cover: float = 45.0) -> NormalizedScene:
    sensing_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return NormalizedScene(
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id=external_id,
        sensing_start=sensing_dt,
        cloud_cover_percent=cloud_cover,
        assets={
            "B04": NormalizedAsset(asset_key="B04", remote_url="https://example.com/b04.tif"),
            "B03": NormalizedAsset(asset_key="B03", remote_url="https://example.com/b03.tif"),
            "B02": NormalizedAsset(asset_key="B02", remote_url="https://example.com/b02.tif"),
        },
    )


def _mock_render_rgb(output_png_path, **kwargs):
    output_png_path.parent.mkdir(parents=True, exist_ok=True)
    output_png_path.write_bytes(b"dummy_test_jpeg_bytes_1234567890")
    return {
        "output_path": output_png_path,
        "width": 512,
        "height": 512,
        "bounds": None,
        "crs": "EPSG:4326",
    }


# 1. Visual data fetch request validation
def test_visual_data_fetch_validation(client: TestClient, db_session: Session):
    wb = _create_test_water_body(db_session, "Validation Lake")

    # Invalid date range (from > to)
    res_range = client.post(
        f"/api/v1/water-bodies/{wb.id}/visual-data/fetch",
        json={"from_date": "2024-12-31", "to_date": "2024-01-01", "image_count": 5},
    )
    assert res_range.status_code == 400

    # Malformed date
    res_malformed = client.post(
        f"/api/v1/water-bodies/{wb.id}/visual-data/fetch",
        json={"from_date": "invalid-date", "to_date": "2024-12-31", "image_count": 5},
    )
    assert res_malformed.status_code == 422

    # Image count < 1
    res_count = client.post(
        f"/api/v1/water-bodies/{wb.id}/visual-data/fetch",
        json={"from_date": "2024-01-01", "to_date": "2024-12-31", "image_count": 0},
    )
    assert res_count.status_code == 422

    # Non-existent water body
    res_404 = client.post(
        "/api/v1/water-bodies/00000000-0000-0000-0000-000000000000/visual-data/fetch",
        json={"from_date": "2024-01-01", "to_date": "2024-12-31", "image_count": 5},
    )
    assert res_404.status_code == 404


# 2. Temporal distribution logic & cloud cover tolerance
def test_temporal_distribution_and_cloud_tolerance(client: TestClient, db_session: Session):
    wb = _create_test_water_body(db_session, "Temporal Test Lake")

    # Mock 12 available scenes across the year with high cloud cover (some 80% clouds!)
    mock_scenes = [
        _make_mock_scene(f"S2_2024_{m:02d}", f"2024-{m:02d}-15", cloud_cover=float(m * 7))
        for m in range(1, 13)
    ]

    # Mock STAC search and renderer to test selection and distribution
    with patch(
        "app.services.satellite.providers.stac.EarthSearchSTACProvider.search_scenes",
        new_callable=AsyncMock,
    ) as mock_stac, patch(
        "app.services.satellite.observation_service.SatelliteObservationService._download_band_asset",
        new_callable=AsyncMock,
    ), patch(
        "app.services.raster.renderer.RGBRenderer.render_rgb",
        side_effect=_mock_render_rgb,
    ):
        mock_stac.return_value = mock_scenes

        # Request 4 distributed images out of 12
        res = client.post(
            f"/api/v1/water-bodies/{wb.id}/visual-data/fetch",
            json={"from_date": "2024-01-01", "to_date": "2024-12-31", "image_count": 4},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["requested_count"] == 4
        assert data["available_count"] == 12
        assert len(data["observations"]) == 4

        # Verify scenes were selected across the time span rather than just the first 4
        obs_dates = [obs["sensing_date"][:10] for obs in data["observations"]]
        # Distinct months across the year
        months = [int(d.split("-")[1]) for d in obs_dates]
        assert len(set(months)) == 4
        assert min(months) <= 3
        assert max(months) >= 10


# 3. Partial availability handling
def test_partial_availability(client: TestClient, db_session: Session):
    wb = _create_test_water_body(db_session, "Partial Lake")

    # Only 3 scenes available
    mock_scenes = [
        _make_mock_scene("S2_P1", "2024-02-01", 10.0),
        _make_mock_scene("S2_P2", "2024-05-01", 20.0),
        _make_mock_scene("S2_P3", "2024-08-01", 30.0),
    ]

    with patch(
        "app.services.satellite.providers.stac.EarthSearchSTACProvider.search_scenes",
        new_callable=AsyncMock,
    ) as mock_stac, patch(
        "app.services.satellite.observation_service.SatelliteObservationService._download_band_asset",
        new_callable=AsyncMock,
    ), patch(
        "app.services.raster.renderer.RGBRenderer.render_rgb",
        side_effect=_mock_render_rgb,
    ):
        mock_stac.return_value = mock_scenes

        # Request 10 observations
        res = client.post(
            f"/api/v1/water-bodies/{wb.id}/visual-data/fetch",
            json={"from_date": "2024-01-01", "to_date": "2024-12-31", "image_count": 10},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["requested_count"] == 10
        assert data["available_count"] == 3
        assert len(data["observations"]) == 3
        assert "Only 3 observations were available" in data["message"]


# 4. Duplicate prevention & reuse
def test_duplicate_observation_prevention(client: TestClient, db_session: Session):
    wb = _create_test_water_body(db_session, "Deduplication Lake")
    mock_scene = _make_mock_scene("S2_DEDUP_01", "2024-03-15", 15.0)

    with patch(
        "app.services.satellite.providers.stac.EarthSearchSTACProvider.search_scenes",
        new_callable=AsyncMock,
    ) as mock_stac, patch(
        "app.services.satellite.observation_service.SatelliteObservationService._download_band_asset",
        new_callable=AsyncMock,
    ), patch(
        "app.services.raster.renderer.RGBRenderer.render_rgb",
        side_effect=_mock_render_rgb,
    ):
        mock_stac.return_value = [mock_scene]

        # First request acquires the observation
        res1 = client.post(
            f"/api/v1/water-bodies/{wb.id}/visual-data/fetch",
            json={"from_date": "2024-01-01", "to_date": "2024-12-31", "image_count": 1},
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["acquired_count"] == 1
        assert data1["reused_count"] == 0

        # Second request reuses the existing observation
        res2 = client.post(
            f"/api/v1/water-bodies/{wb.id}/visual-data/fetch",
            json={"from_date": "2024-01-01", "to_date": "2024-12-31", "image_count": 1},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["acquired_count"] == 0
        assert data2["reused_count"] == 1
        assert data1["observations"][0]["id"] == data2["observations"][0]["id"]

        # Verify DB has only 1 observation record
        count = db_session.execute(
            select(func.count(SatelliteObservation.id)).where(
                SatelliteObservation.water_body_id == wb.id
            )
        ).scalar()
        assert count == 1


# 5. Temporal analysis endpoint & extensible indicators
def test_temporal_analysis_endpoint(client: TestClient, db_session: Session):
    wb = _create_test_water_body(db_session, "Analysis Lake")

    # Pre-populate two observations directly in DB
    obs1 = SatelliteObservation(
        water_body_id=wb.id,
        satellite="Sentinel-2",
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2_ANALYSIS_01",
        sensing_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
        cloud_cover_percent=12.0,
        local_visual_path="water_bodies/test/rgb1.jpg",
        derived_water_area_sq_km=82.0,
        status="ready",
    )
    obs2 = SatelliteObservation(
        water_body_id=wb.id,
        satellite="Sentinel-2",
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2_ANALYSIS_02",
        sensing_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
        cloud_cover_percent=35.0,
        local_visual_path="water_bodies/test/rgb2.jpg",
        derived_water_area_sq_km=78.5,
        status="ready",
    )
    db_session.add_all([obs1, obs2])
    db_session.commit()

    res = client.get(f"/api/v1/analysis/water-bodies/{wb.id}")
    assert res.status_code == 200
    data = res.json()

    assert data["water_body_id"] == wb.id
    assert data["total_observations"] == 2
    assert len(data["timeline"]) == 2

    # Verify chronological ordering
    assert data["timeline"][0]["sensing_date_str"] == "2024-01-15"
    assert data["timeline"][1]["sensing_date_str"] == "2024-06-15"

    # Water extent change from previous
    assert data["timeline"][0]["water_extent_sq_km"] == 82.0
    assert data["timeline"][0]["change_from_previous_sq_km"] is None
    assert data["timeline"][1]["water_extent_sq_km"] == 78.5
    assert data["timeline"][1]["change_from_previous_sq_km"] == pytest.approx(-3.5, abs=0.01)

    # Invariant: No fake water quality numbers! All indicators marked "COMING IN ANALYSIS PHASE"
    assert "turbidity" in data["indicators"]
    assert "chlorophyll" in data["indicators"]
    assert "algae" in data["indicators"]
    assert "anomaly" in data["indicators"]

    for ind_key, ind_val in data["indicators"].items():
        assert ind_val["status"] == "coming_soon"
        assert ind_val["message"] == "COMING IN ANALYSIS PHASE"


# 6. Available observations metadata-only search & cloud filtering
def test_available_observations_metadata_search(client: TestClient, db_session: Session):
    wb = _create_test_water_body(db_session, "Metadata Search Lake")

    # 5 scenes with varying cloud covers: 5%, 15%, 35%, 60%, 85%
    mock_scenes = [
        _make_mock_scene("S2_C05", "2024-01-10", 5.0),
        _make_mock_scene("S2_C15", "2024-02-10", 15.0),
        _make_mock_scene("S2_C35", "2024-03-10", 35.0),
        _make_mock_scene("S2_C60", "2024-04-10", 60.0),
        _make_mock_scene("S2_C85", "2024-05-10", 85.0),
    ]

    with patch(
        "app.services.satellite.providers.stac.EarthSearchSTACProvider.search_scenes",
        new_callable=AsyncMock,
    ) as mock_stac, patch(
        "app.services.raster.renderer.RGBRenderer.render_rgb"
    ) as mock_render:
        mock_stac.return_value = mock_scenes

        # Default search: max_cloud <= 40%, include_high_cloud = False
        res = client.get(
            f"/api/v1/water-bodies/{wb.id}/visual-data/available?from_date=2024-01-01&to_date=2024-12-31"
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total_found"] == 3
        scene_ids = [it["scene_id"] for it in data["items"]]
        assert scene_ids == ["S2_C35", "S2_C15", "S2_C05"]  # newest first
        # Verify observation_id, scene_id, and id are all present and identical non-empty strings
        for it in data["items"]:
            assert it["observation_id"] == it["scene_id"] == it["id"]
            assert len(it["observation_id"]) > 0
            assert "platform" in it
            assert "already_acquired" in it
            assert "is_already_available" in it
        assert data["items"][0]["quality_label"] == "ACCEPTABLE"
        assert data["items"][1]["quality_label"] == "CLEAR"
        assert data["items"][2]["quality_label"] == "VERY CLEAR"

        # Invariant: NO raster downloads or renders occurred during metadata search
        mock_render.assert_not_called()

        # Search with include_high_cloud = True
        res_high = client.get(
            f"/api/v1/water-bodies/{wb.id}/visual-data/available?from_date=2024-01-01&to_date=2024-12-31&include_high_cloud=true"
        )
        assert res_high.status_code == 200
        data_high = res_high.json()
        assert data_high["total_found"] == 5
        high_cloud_items = [it for it in data_high["items"] if it["is_high_cloud"]]
        assert len(high_cloud_items) == 2
        for it in high_cloud_items:
            assert it["quality_label"] == "HIGH CLOUD"

        # Sorting: lowest_cloud
        res_lowest = client.get(
            f"/api/v1/water-bodies/{wb.id}/visual-data/available?from_date=2024-01-01&to_date=2024-12-31&sort=lowest_cloud"
        )
        assert res_lowest.status_code == 200
        data_lowest = res_lowest.json()
        clouds = [it["cloud_cover_percent"] for it in data_lowest["items"]]
        assert clouds == sorted(clouds)


# 7. Fetch selected validation and max 20 limit
def test_fetch_selected_validation_and_max_limit(client: TestClient, db_session: Session):
    wb = _create_test_water_body(db_session, "Selection Validation Lake")

    # Empty selection rejected
    res_empty = client.post(
        f"/api/v1/water-bodies/{wb.id}/visual-data/fetch-selected",
        json={"observation_ids": []},
    )
    assert res_empty.status_code == 422

    # Null in observation_ids rejected with 422
    res_null = client.post(
        f"/api/v1/water-bodies/{wb.id}/visual-data/fetch-selected",
        json={"observation_ids": [None]},
    )
    assert res_null.status_code == 422
    assert "must be a valid non-empty string" in str(res_null.json())

    # Empty string in observation_ids rejected with 422
    res_blank = client.post(
        f"/api/v1/water-bodies/{wb.id}/visual-data/fetch-selected",
        json={"observation_ids": ["   "]},
    )
    assert res_blank.status_code == 422
    assert "must be a valid non-empty string" in str(res_blank.json())

    # Excessive selection (>20) rejected
    too_many_ids = [f"S2_EXCESS_{i:02d}" for i in range(25)]
    res_too_many = client.post(
        f"/api/v1/water-bodies/{wb.id}/visual-data/fetch-selected",
        json={"observation_ids": too_many_ids},
    )
    assert res_too_many.status_code == 422
    assert "Maximum 20 observations" in str(res_too_many.json())

    # Non-existent water body
    res_404 = client.post(
        "/api/v1/water-bodies/00000000-0000-0000-0000-000000000000/visual-data/fetch-selected",
        json={"observation_ids": ["S2_TEST_01"]},
    )
    assert res_404.status_code == 404


# 8. Fetch selected observations job execution and real progress
def test_fetch_selected_observations_job_and_progress(client: TestClient, db_session: Session):
    wb = _create_test_water_body(db_session, "Job Progress Lake")
    scene1 = _make_mock_scene("S2_JOB_01", "2024-02-15", 12.0)
    scene2 = _make_mock_scene("S2_JOB_02", "2024-03-15", 8.0)

    with patch(
        "app.services.satellite.providers.stac.EarthSearchSTACProvider.search_scenes",
        new_callable=AsyncMock,
    ) as mock_stac, patch(
        "app.services.raster.renderer.RGBRenderer.render_rgb",
        side_effect=_mock_render_rgb,
    ):
        mock_stac.return_value = [scene1, scene2]

        res = client.post(
            f"/api/v1/water-bodies/{wb.id}/visual-data/fetch-selected",
            json={"observation_ids": ["S2_JOB_01", "S2_JOB_02"]},
        )
        assert res.status_code == 202
        job_data = res.json()
        assert "job_id" in job_data
        assert job_data["total"] == 2
        job_id = job_data["job_id"]

        status_res = client.get(f"/api/v1/water-bodies/{wb.id}/visual-data/jobs/{job_id}")
        assert status_res.status_code == 200
        final_status = status_res.json()
        print("DEBUG final_status:", final_status)
        assert final_status["status"] == "completed"
        assert final_status["completed"] == 2
        assert final_status["percent"] == 100
        assert len(final_status["results"]) == 2


# 9. Quality check rejection of unusable visual output
def test_unusable_visual_output_rejection(client: TestClient, db_session: Session):
    wb = _create_test_water_body(db_session, "Quality Check Lake")
    scene = _make_mock_scene("S2_UNUSABLE_01", "2024-04-15", 98.0)

    def _mock_unusable_render(output_png_path, **kwargs):
        return {
            "output_path": output_png_path,
            "width": 100,
            "height": 100,
            "bounds": None,
            "crs": "EPSG:4326",
            "quality_valid": False,
            "quality_reason": "Solid cloud whiteout (>90% saturated)",
        }

    with patch(
        "app.services.satellite.providers.stac.EarthSearchSTACProvider.search_scenes",
        new_callable=AsyncMock,
    ) as mock_stac, patch(
        "app.services.raster.renderer.RGBRenderer.render_rgb",
        side_effect=_mock_unusable_render,
    ):
        mock_stac.return_value = [scene]

        res = client.post(
            f"/api/v1/water-bodies/{wb.id}/visual-data/fetch-selected",
            json={"observation_ids": ["S2_UNUSABLE_01"]},
        )
        assert res.status_code == 202
        job_id = res.json()["job_id"]

        status_res = client.get(f"/api/v1/water-bodies/{wb.id}/visual-data/jobs/{job_id}")
        assert status_res.status_code == 200
        final_st = status_res.json()
        assert final_st["failed"] == 1
        assert len(final_st["errors"]) == 1
        assert "UNUSABLE VISUAL OUTPUT" in final_st["errors"][0]["error"]

        # Ensure no database record was stored for the rejected observation
        count = db_session.execute(
            select(func.count(SatelliteObservation.id)).where(
                SatelliteObservation.water_body_id == wb.id
            )
        ).scalar()
        assert count == 0


# 10. Analysis quality labels and unmeasured extent integrity
def test_analysis_quality_labels_and_unmeasured_extent(client: TestClient, db_session: Session):
    wb = _create_test_water_body(db_session, "Extent Integrity Lake")

    obs = SatelliteObservation(
        water_body_id=wb.id,
        satellite="Sentinel-2",
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2_EXTENT_01",
        sensing_date=datetime(2024, 5, 20, tzinfo=timezone.utc),
        cloud_cover_percent=7.5,
        local_visual_path="water_bodies/test/rgb_extent.jpg",
        derived_water_area_sq_km=None,  # Segmentation has not run
        status="ready",
    )
    db_session.add(obs)
    db_session.commit()

    res = client.get(f"/api/v1/analysis/water-bodies/{wb.id}")
    assert res.status_code == 200
    data = res.json()

    item = data["timeline"][0]
    assert item["quality_label"] == "VERY CLEAR"
    assert item["cloud_cover_percent"] == 7.5
    assert item["water_extent_sq_km"] is not None
    assert item["is_demo_extent"] is True
    assert item["is_extent_measured"] is False
    assert item["registered_area_sq_km"] == wb.area_sq_km


def test_observation_image_filters_and_fallback(client: TestClient, db_session: Session, tmp_path):
    wb = _create_test_water_body(db_session, "Filter Test Lake")

    # Create dummy observation directory and rgb.jpg
    obs_dir = tmp_path / "water_bodies" / wb.id / "observations" / "S2_FILTER_TEST"
    obs_dir.mkdir(parents=True, exist_ok=True)
    rgb_file = obs_dir / "rgb.jpg"

    from PIL import Image
    im = Image.new("RGB", (100, 100), color=(50, 120, 200))
    im.save(rgb_file, "JPEG")

    obs = SatelliteObservation(
        water_body_id=wb.id,
        satellite="Sentinel-2",
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2_FILTER_TEST",
        sensing_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
        cloud_cover_percent=2.0,
        local_visual_path=str(rgb_file.relative_to(tmp_path)).replace("\\", "/"),
        status="ready",
    )
    db_session.add(obs)
    db_session.commit()

    # Monkeypatch storage data_dir
    with patch("app.services.satellite.observation_service.settings.DATA_DIR", tmp_path):
        # 1. Natural filter
        res_nat = client.get(f"/api/v1/water-bodies/{wb.id}/observations/{obs.id}/image?filter=natural")
        assert res_nat.status_code == 200
        assert res_nat.headers["content-type"] == "image/jpeg"

        # 2. Water emphasis filter
        res_water = client.get(f"/api/v1/water-bodies/{wb.id}/observations/{obs.id}/image?filter=water_emphasis")
        assert res_water.status_code == 200
        assert res_water.headers["content-type"] == "image/jpeg"
        assert (obs_dir / "rgb_water_emphasis.jpg").exists()

        # 3. Contrast filter
        res_contrast = client.get(f"/api/v1/water-bodies/{wb.id}/observations/{obs.id}/image?filter=contrast")
        assert res_contrast.status_code == 200
        assert res_contrast.headers["content-type"] == "image/jpeg"
        assert (obs_dir / "rgb_contrast.jpg").exists()

        # 4. NIR filter (unavailable band fallback -> returns informative SVG)
        res_nir = client.get(f"/api/v1/water-bodies/{wb.id}/observations/{obs.id}/image?filter=nir")
        assert res_nir.status_code == 200
        assert "image/svg+xml" in res_nir.headers["content-type"]
        assert b"Near-Infrared (B08) Not Acquired" in res_nir.content

