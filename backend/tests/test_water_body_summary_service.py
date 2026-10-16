import pytest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient

from app.db.models.water_body import WaterBody
from app.db.models.satellite_observation import SatelliteObservation
from app.services.water_body_summary_service import WaterBodySummaryService
from app.services.water_quality_summary_service import WaterQualitySummaryService


@pytest.fixture
def summary_test_data(db_session, tmp_path):
    """Sets up test water bodies and observations with actual dummy files."""
    wb1 = WaterBody(
        id=str(uuid.uuid4()),
        name="Chilika Lake",
        normalized_name="chilika lake",
        source="osm",
        water_body_type="lagoon",
        country="India",
        state_province="Odisha",
        district="Puri",
        city="Chilika",
        area_sq_km=1165.0,
        centroid_lat=19.72,
        centroid_lon=85.32,
    )
    wb2 = WaterBody(
        id=str(uuid.uuid4()),
        name="Ooty Lake",
        normalized_name="ooty lake",
        source="osm",
        water_body_type="lake",
        country="India",
        state_province="Tamil Nadu",
        district="Nilgiris",
        city="Ooty",
        area_sq_km=0.26,
        centroid_lat=11.41,
        centroid_lon=76.69,
    )
    wb3 = WaterBody(
        id=str(uuid.uuid4()),
        name="Salim Ali Lake",
        normalized_name="salim ali lake",
        source="osm",
        area_sq_km=None,  # Missing area test
    )
    db_session.add_all([wb1, wb2, wb3])
    db_session.commit()

    # Create dummy observation image files on tmp_path
    obs_dir = tmp_path / "water_bodies" / wb1.id / "observations" / "scene_01"
    obs_dir.mkdir(parents=True, exist_ok=True)
    img_file = obs_dir / "rgb.jpg"
    img_file.write_bytes(b"dummy_jpeg_data")

    # Add observations to wb1
    obs1 = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb1.id,
        external_scene_id="scene_01",
        sensing_date=datetime(2026, 10, 10, 5, 30, tzinfo=timezone.utc),
        cloud_cover_percent=5.1,
        derived_water_area_sq_km=1120.0,
        local_visual_path=f"water_bodies/{wb1.id}/observations/scene_01/rgb.jpg",
    )
    obs2 = SatelliteObservation(
        id=str(uuid.uuid4()),
        water_body_id=wb1.id,
        external_scene_id="scene_02",
        sensing_date=datetime(2026, 9, 20, 5, 30, tzinfo=timezone.utc),
        cloud_cover_percent=12.0,
        derived_water_area_sq_km=1140.0,
        local_visual_path=f"water_bodies/{wb1.id}/observations/scene_02/rgb.jpg",  # Missing on disk
    )
    db_session.add_all([obs1, obs2])
    db_session.commit()

    return wb1, wb2, wb3, img_file, tmp_path


def test_list_and_find_water_bodies(db_session, summary_test_data):
    wb1, wb2, wb3, _, tmp_path = summary_test_data
    service = WaterBodySummaryService(db_session, data_dir=tmp_path)

    all_wbs = service.list_water_bodies()
    assert len(all_wbs) == 3

    # Exact match
    found = service.find_water_bodies("Chilika Lake")
    assert len(found) == 1
    assert found[0].id == wb1.id

    # Case-insensitive + whitespace tolerant
    found = service.find_water_bodies("  CHILIKA LAKE   ")
    assert len(found) == 1
    assert found[0].id == wb1.id

    # Partial / substring multiple matches
    matches = service.find_water_bodies("Lake")
    assert len(matches) == 3

    # No match
    no_matches = service.find_water_bodies("NonExistentWaterBody")
    assert len(no_matches) == 0


def test_water_volume_logic(db_session, summary_test_data):
    wb1, wb2, wb3, _, tmp_path = summary_test_data
    service = WaterBodySummaryService(db_session, data_dir=tmp_path)

    # Large water body (>50 km²)
    vol1, is_est1, note1 = service.get_water_volume_summary(wb1)
    assert "billion m³" in vol1
    assert is_est1 is True
    assert "Demo estimate" in note1

    # Small water body (<1 km²)
    vol2, is_est2, note2 = service.get_water_volume_summary(wb2)
    assert "million m³" in vol2
    assert is_est2 is True

    # Missing area
    vol3, is_est3, note3 = service.get_water_volume_summary(wb3)
    assert vol3 == "Not available"
    assert is_est3 is False


def test_monitoring_frequency_logic(db_session, summary_test_data):
    wb1, _, _, _, tmp_path = summary_test_data
    service = WaterBodySummaryService(db_session, data_dir=tmp_path)

    obs_list = service.obs_repo.list_for_water_body(wb1.id)
    obs_list.sort(key=lambda o: o.sensing_date)
    freq, start_d, end_d = service.get_monitoring_frequency(obs_list)

    assert "days" in freq or "observations available" in freq
    assert start_d is not None
    assert end_d is not None


def test_latest_visual_observation_selection(db_session, summary_test_data):
    """Verify that only observations whose image file actually exists on disk are returned."""
    wb1, _, _, img_file, tmp_path = summary_test_data
    service = WaterBodySummaryService(db_session, data_dir=tmp_path)

    res = service.get_latest_visual_observation(wb1.id)
    assert res is not None
    obs, file_path = res
    assert obs.external_scene_id == "scene_01"
    assert file_path.resolve() == img_file.resolve()

    # If the file is deleted, it should return None
    img_file.unlink()
    res_after = service.get_latest_visual_observation(wb1.id)
    assert res_after is None


def test_water_quality_summary_service():
    """Verify water quality proxy translations."""
    # 1. Turbid
    res_turbid = WaterQualitySummaryService.summarize_indicators({"ndti": {"classification": "HIGH"}})
    assert res_turbid.label == "Turbid"
    assert "cloudy" in res_turbid.simple_view

    # 2. Elevated chlorophyll
    res_chla = WaterQualitySummaryService.summarize_indicators({"ndci": {"classification": "HIGH"}})
    assert "chlorophyll-a" in res_chla.label.lower()

    # 3. Algal proxy
    res_algae = WaterQualitySummaryService.summarize_indicators({"fai": {"classification": "ELEVATED"}})
    assert "algal" in res_algae.label.lower()

    # 4. Anomaly
    res_anom = WaterQualitySummaryService.summarize_indicators({"anomaly": {"classification": "ANOMALY"}})
    assert "anomaly" in res_anom.label.lower()

    # 5. Clear
    res_clear = WaterQualitySummaryService.summarize_indicators({"ndti": {"classification": "LOW"}, "ndci": {"classification": "LOW"}})
    assert "clear" in res_clear.label.lower()
    assert "NOT mean it is safe to drink" in res_clear.simple_view

    # 6. Insufficient data
    res_empty = WaterQualitySummaryService.summarize_indicators({})
    assert res_empty.label == "Insufficient data"


def test_water_body_summary_generation_and_formatting(db_session, summary_test_data):
    wb1, _, _, _, tmp_path = summary_test_data
    service = WaterBodySummaryService(db_session, data_dir=tmp_path)

    summary = service.get_water_body_summary(wb1.id)
    assert summary.name == "Chilika Lake"
    assert "Odisha, India" in summary.location
    assert "~1.16e+03 km²" in summary.surface_area_text or "1,165" in summary.surface_area_text
    assert "5.1%" in summary.cloud_cover
    assert summary.has_stored_visual_image is True

    # Format text
    text_msg = service.format_telegram_summary_message(summary)
    assert "CHILIKA LAKE" in text_msg
    assert "Location" in text_msg
    assert "Surface Area" in text_msg
    assert "Water Quality" in text_msg
    assert "Simple view:" in text_msg
    # Ensure internal paths are NOT in user message
    assert "data/water_bodies" not in text_msg
    assert "C:\\" not in text_msg


def test_api_water_body_summary_endpoint(client: TestClient, db_session, summary_test_data):
    wb1, _, _, _, _ = summary_test_data
    resp = client.get(f"/api/v1/water-bodies/{wb1.id}/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Chilika Lake"
    assert "location" in data
    assert "surface_area_text" in data
    assert "water_volume" in data
    assert "observation_frequency" in data
    assert "water_quality_label" in data
    assert "water_quality_simple_text" in data
    # Ensure no internal filesystem paths are exposed
    assert "latest_image_path" not in data
    assert "C:\\" not in str(data)
