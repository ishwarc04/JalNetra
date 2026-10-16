"""
Integration tests for Map API endpoints (Phase 4).
"""
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.water_body import WaterBody
from app.db.models.satellite_scene import SatelliteScene
from app.db.models.satellite_asset import SatelliteAsset
from tests.test_raster_service import create_synthetic_geotiff


def test_map_api_water_bodies_geojson(client: TestClient, db_session: Session):
    """Verifies GET /api/v1/map/water-bodies/geojson returns a valid GeoJSON FeatureCollection."""
    wb = WaterBody(
        name="Map Test Lake",
        normalized_name="map test lake",
        country="India",
        source="manual",
        source_id="map-wb-1",
        centroid_lat=20.0,
        centroid_lon=85.0,
        min_lat=19.9,
        min_lon=84.9,
        max_lat=20.1,
        max_lon=85.1,
        geometry_geojson='{"type": "Polygon", "coordinates": [[[84.9, 19.9], [85.1, 19.9], [85.1, 20.1], [84.9, 20.1], [84.9, 19.9]]]}',
    )
    db_session.add(wb)
    db_session.commit()

    resp = client.get("/api/v1/map/water-bodies/geojson")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) >= 1
    feat = next(f for f in data["features"] if f["properties"]["id"] == wb.id)
    assert feat["properties"]["name"] == "Map Test Lake"
    assert feat["geometry"]["type"] == "Polygon"


def test_map_api_scenes_list(client: TestClient, db_session: Session):
    """Verifies GET /api/v1/map/scenes?water_body_id=... returns registered scenes."""
    scene = SatelliteScene(
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2A_MAP_SCENE_TEST",
        sensing_start=datetime.now(timezone.utc),
        cloud_cover_percent=1.2,
        status="downloaded",
        bbox_min_lat=19.0,
        bbox_min_lon=85.0,
        bbox_max_lat=20.0,
        bbox_max_lon=86.0,
        footprint_geojson='{"type": "Polygon", "coordinates": [[[85.0, 19.0], [86.0, 19.0], [86.0, 20.0], [85.0, 20.0], [85.0, 19.0]]]}',
    )
    db_session.add(scene)
    db_session.commit()

    resp = client.get(f"/api/v1/map/scenes?water_body_id=dummy-id")
    assert resp.status_code == 200
    scenes = resp.json()
    assert len(scenes) >= 1
    found = next(s for s in scenes if s["external_scene_id"] == "S2A_MAP_SCENE_TEST")
    assert found["cloud_cover_percent"] == 1.2
    assert found["footprint"] is not None


def test_map_api_raster_metadata_and_rgb(client: TestClient, db_session: Session, tmp_path: Path, monkeypatch):
    """Verifies /api/v1/map/scenes/{scene_id}/metadata and /rgb endpoints."""
    import app.services.raster.service as raster_svc_module

    # Monkeypatch data_dir in raster service
    monkeypatch.setattr(raster_svc_module.settings, "DATA_DIR", str(tmp_path))

    scene_id = "map-scene-test-uuid"
    scene_dir = tmp_path / "scenes" / scene_id / "assets"
    
    scene = SatelliteScene(
        id=scene_id,
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2A_TEST_FULL_FLOW",
        sensing_start=datetime.now(timezone.utc),
        status="downloaded",
    )
    db_session.add(scene)

    for band in ["B04", "B03", "B02"]:
        tif = scene_dir / f"{band}.tif"
        create_synthetic_geotiff(tif, width=32, height=32)
        asset = SatelliteAsset(
            scene_id=scene_id,
            asset_key=band,
            asset_type="image/tiff",
            local_path=f"scenes/{scene_id}/assets/{band}.tif",
            status="downloaded",
            file_size_bytes=tif.stat().st_size,
        )
        db_session.add(asset)
    db_session.commit()

    # 1. Metadata check
    meta_resp = client.get(f"/api/v1/map/scenes/{scene_id}/metadata")
    assert meta_resp.status_code == 200
    meta = meta_resp.json()
    assert meta["rgb_available"] is True
    assert meta["geographic_bounds"] is not None

    # 2. RGB rendering check
    rgb_resp = client.get(f"/api/v1/map/scenes/{scene_id}/rgb")
    assert rgb_resp.status_code == 200
    rgb_data = rgb_resp.json()
    assert rgb_data["crs"] == "EPSG:4326"
    assert rgb_data["width"] > 0
    assert "image_url" in rgb_data

    # 3. Stream RGB image check
    img_resp = client.get(f"/api/v1/map/scenes/{scene_id}/rgb/image")
    assert img_resp.status_code == 200
    assert img_resp.headers["content-type"] == "image/png"
    assert len(img_resp.content) > 0

    # 4. Focused water body RGB rendering check
    wb = WaterBody(
        id="wb-focused-api-test",
        name="API Focused Lake",
        normalized_name="api focused lake",
        source="test",
        source_id="test-api-lake",
        min_lon=84.95,
        min_lat=19.95,
        max_lon=85.05,
        max_lat=20.05,
    )
    db_session.add(wb)
    db_session.commit()

    focused_resp = client.get(f"/api/v1/map/scenes/{scene_id}/rgb?water_body_id={wb.id}")
    assert focused_resp.status_code == 200
    focused_data = focused_resp.json()
    assert focused_data["is_focused"] is True
    assert focused_data["water_body_id"] == wb.id
    assert f"water_body_id={wb.id}" in focused_data["image_url"]

    focused_img_resp = client.get(f"/api/v1/map/scenes/{scene_id}/rgb/image?water_body_id={wb.id}")
    assert focused_img_resp.status_code == 200
    assert focused_img_resp.headers["content-type"] == "image/png"


def test_map_api_security_path_traversal(client: TestClient):
    """Verifies that arbitrary path traversal attempts return 404/rejection."""
    resp = client.get("/api/v1/map/scenes/../../etc/passwd/rgb/image")
    assert resp.status_code in [404, 422]


def test_map_api_bbox_and_padding_validation(client: TestClient):
    """Verifies validation on bbox and padding_percent query parameters."""
    dummy_scene = "any-scene-id"

    # 1. Non-numeric bbox
    resp1 = client.get(f"/api/v1/map/scenes/{dummy_scene}/rgb?bbox=abc,def,1,2")
    assert resp1.status_code == 400
    assert "numeric coordinates" in resp1.json()["error"]["message"]

    # 2. Too few coordinates
    resp2 = client.get(f"/api/v1/map/scenes/{dummy_scene}/rgb?bbox=84.0,19.0,85.0")
    assert resp2.status_code == 400
    assert "exactly 4 coordinates" in resp2.json()["error"]["message"]

    # 3. West >= East
    resp3 = client.get(f"/api/v1/map/scenes/{dummy_scene}/rgb?bbox=85.0,19.0,84.0,20.0")
    assert resp3.status_code == 400
    assert "West coordinate must be less than East" in resp3.json()["error"]["message"]

    # 4. South >= North
    resp4 = client.get(f"/api/v1/map/scenes/{dummy_scene}/rgb?bbox=84.0,20.0,85.0,19.0")
    assert resp4.status_code == 400
    assert "South coordinate must be less than North" in resp4.json()["error"]["message"]

    # 5. Out of bounds coords
    resp5 = client.get(f"/api/v1/map/scenes/{dummy_scene}/rgb?bbox=-200,19.0,85.0,20.0")
    assert resp5.status_code == 400

    # 6. Negative padding
    resp6 = client.get(f"/api/v1/map/scenes/{dummy_scene}/rgb?padding_percent=-5")
    assert resp6.status_code == 400
    assert "between 0 and 100" in resp6.json()["error"]["message"]

    # 7. Excessive padding > 100
    resp7 = client.get(f"/api/v1/map/scenes/{dummy_scene}/rgb?padding_percent=120")
    assert resp7.status_code == 400
    assert "between 0 and 100" in resp7.json()["error"]["message"]


def test_map_api_manual_aoi_and_custom_padding(client: TestClient, db_session: Session, tmp_path: Path, monkeypatch):
    """Verifies manual AOI bbox and custom padding rendering via Map API."""
    import app.services.raster.service as raster_svc_module

    monkeypatch.setattr(raster_svc_module.settings, "DATA_DIR", str(tmp_path))

    scene_id = "map-scene-aoi-test"
    scene_dir = tmp_path / "scenes" / scene_id / "assets"

    scene = SatelliteScene(
        id=scene_id,
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2A_AOI_TEST",
        sensing_start=datetime.now(timezone.utc),
        status="downloaded",
    )
    db_session.add(scene)

    for band in ["B04", "B03", "B02"]:
        tif = scene_dir / f"{band}.tif"
        create_synthetic_geotiff(tif, width=32, height=32)
        asset = SatelliteAsset(
            scene_id=scene_id,
            asset_key=band,
            asset_type="image/tiff",
            local_path=f"scenes/{scene_id}/assets/{band}.tif",
            status="downloaded",
            file_size_bytes=tif.stat().st_size,
        )
        db_session.add(asset)

    wb = WaterBody(
        id="wb-aoi-pad-test",
        name="AOI Pad Lake",
        normalized_name="aoi pad lake",
        source="test",
        source_id="test-pad-lake",
        min_lon=84.95,
        min_lat=19.95,
        max_lon=85.05,
        max_lat=20.05,
    )
    db_session.add(wb)
    db_session.commit()

    # Manual AOI bbox test
    aoi_resp = client.get(f"/api/v1/map/scenes/{scene_id}/rgb?bbox=84.95,19.95,85.05,20.05")
    assert aoi_resp.status_code == 200
    aoi_data = aoi_resp.json()
    assert aoi_data["is_focused"] is True
    assert "bbox=84.95" in aoi_data["image_url"]

    # Stream manual AOI image
    aoi_img_resp = client.get(f"/api/v1/map/scenes/{scene_id}/rgb/image?bbox=84.95,19.95,85.05,20.05")
    assert aoi_img_resp.status_code == 200
    assert aoi_img_resp.headers["content-type"] == "image/png"

    # Custom padding percentage test (25%)
    pad_resp = client.get(f"/api/v1/map/scenes/{scene_id}/rgb?water_body_id={wb.id}&padding_percent=25")
    assert pad_resp.status_code == 200
    pad_data = pad_resp.json()
    assert pad_data["is_focused"] is True
    assert "padding_percent=25.0" in pad_data["image_url"]

    # Stream custom padding image
    pad_img_resp = client.get(f"/api/v1/map/scenes/{scene_id}/rgb/image?water_body_id={wb.id}&padding_percent=25")
    assert pad_img_resp.status_code == 200
    assert pad_img_resp.headers["content-type"] == "image/png"


def test_water_body_scene_isolation_and_spatial_sorting(client: TestClient, db_session: Session):
    """
    Verifies that when scenes are queried for a water body, only geographically covering
    scenes have covers_water_body=True, and covering scenes sort first.
    Prevents cross-water-body scene contamination (e.g. Khadakwasla scene showing for Salim Ali Lake).
    """
    # 1. Water Body A: Salim Ali Lake (Aurangabad, lon ~75.34, lat ~19.90)
    wb_salim = WaterBody(
        name="Salim Ali Lake",
        normalized_name="salim ali lake",
        country="India",
        source="osm",
        source_id="salim-lake-iso-1",
        centroid_lat=19.8988,
        centroid_lon=75.3408,
        min_lon=75.338,
        min_lat=19.897,
        max_lon=75.343,
        max_lat=19.900,
        geometry_geojson='{"type": "Polygon", "coordinates": [[[75.338, 19.897], [75.343, 19.897], [75.343, 19.900], [75.338, 19.900], [75.338, 19.897]]]}',
    )
    # 2. Water Body B: Khadakwasla Dam (Pune, lon ~73.76, lat ~18.44)
    wb_khadak = WaterBody(
        name="Khadakwasla Dam",
        normalized_name="khadakwasla dam",
        country="India",
        source="osm",
        source_id="khadak-dam-iso-2",
        centroid_lat=18.442,
        centroid_lon=73.762,
        min_lon=73.71,
        min_lat=18.40,
        max_lon=73.80,
        max_lat=18.48,
        geometry_geojson='{"type": "Polygon", "coordinates": [[[73.71, 18.40], [73.80, 18.40], [73.80, 18.48], [73.71, 18.48], [73.71, 18.40]]]}',
    )
    db_session.add_all([wb_salim, wb_khadak])
    db_session.commit()

    # Scene A: covers Salim Ali (lon 75-76, lat 19.5-20.5)
    scene_salim = SatelliteScene(
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2A_T43QEC_SALIM_TEST",
        sensing_start=datetime.now(timezone.utc),
        status="downloaded",
        bbox_min_lon=75.0,
        bbox_min_lat=19.5,
        bbox_max_lon=76.0,
        bbox_max_lat=20.5,
        footprint_geojson='{"type": "Polygon", "coordinates": [[[75.0, 19.5], [76.0, 19.5], [76.0, 20.5], [75.0, 20.5], [75.0, 19.5]]]}',
    )
    # Scene B: covers Khadakwasla (lon 73.5-74.0, lat 18.2-18.6)
    scene_khadak = SatelliteScene(
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2B_T43QCA_KHADAK_TEST",
        sensing_start=datetime.now(timezone.utc),
        status="downloaded",
        bbox_min_lon=73.5,
        bbox_min_lat=18.2,
        bbox_max_lon=74.0,
        bbox_max_lat=18.6,
        footprint_geojson='{"type": "Polygon", "coordinates": [[[73.5, 18.2], [74.0, 18.2], [74.0, 18.6], [73.5, 18.6], [73.5, 18.2]]]}',
    )
    db_session.add_all([scene_salim, scene_khadak])
    db_session.commit()

    # Query scenes for Salim Ali Lake
    resp_salim = client.get(f"/api/v1/map/scenes?water_body_id={wb_salim.id}")
    assert resp_salim.status_code == 200
    scenes_salim = resp_salim.json()
    assert len(scenes_salim) >= 2
    # First scene MUST be the one covering Salim Ali Lake
    assert scenes_salim[0]["scene_id"] == scene_salim.id
    assert scenes_salim[0]["covers_water_body"] is True

    # Khadak scene in Salim query must have covers_water_body = False
    khadak_in_salim = next(s for s in scenes_salim if s["scene_id"] == scene_khadak.id)
    assert khadak_in_salim["covers_water_body"] is False

    # Query scenes for Khadakwasla Dam
    resp_khadak = client.get(f"/api/v1/map/scenes?water_body_id={wb_khadak.id}")
    assert resp_khadak.status_code == 200
    scenes_khadak = resp_khadak.json()
    assert len(scenes_khadak) >= 2
    # First scene MUST be the one covering Khadakwasla
    assert scenes_khadak[0]["scene_id"] == scene_khadak.id
    assert scenes_khadak[0]["covers_water_body"] is True

    # Salim scene in Khadak query must have covers_water_body = False
    salim_in_khadak = next(s for s in scenes_khadak if s["scene_id"] == scene_salim.id)
    assert salim_in_khadak["covers_water_body"] is False


def test_spatial_cross_water_body_rejection(client: TestClient, db_session: Session, tmp_path: Path, monkeypatch):
    """
    Verifies that requesting RGB for a scene with a non-overlapping water body
    or non-overlapping bbox is rejected with 400/404 error and explanatory detail.
    """
    import app.services.raster.service as raster_svc_module
    monkeypatch.setattr(raster_svc_module.settings, "DATA_DIR", str(tmp_path))

    # Water Body in Mumbai (lon ~72.8, lat ~19.0)
    wb_mumbai = WaterBody(
        name="Mumbai Lake",
        normalized_name="mumbai lake",
        source="osm",
        source_id="mumbai-lake-1",
        min_lon=72.80,
        min_lat=19.00,
        max_lon=72.85,
        max_lat=19.05,
    )
    # Scene in Odisha / Chilika (lon ~85.0 - 85.5, lat ~19.3 - 19.8)
    scene = SatelliteScene(
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2A_CHILIKA_MISMATCH",
        sensing_start=datetime.now(timezone.utc),
        status="downloaded",
        bbox_min_lon=85.0,
        bbox_min_lat=19.3,
        bbox_max_lon=85.5,
        bbox_max_lat=19.8,
    )
    db_session.add_all([wb_mumbai, scene])
    db_session.commit()

    # Attempt to request RGB for Chilika scene using Mumbai water body ID
    resp = client.get(f"/api/v1/map/scenes/{scene.id}/rgb?water_body_id={wb_mumbai.id}")
    assert resp.status_code in (400, 404)
    data = resp.json()
    msg = data.get("error", {}).get("message", "") or data.get("detail", "")
    assert "does not geographically intersect" in msg

    # Attempt to request RGB with non-overlapping manual AOI
    resp_aoi = client.get(f"/api/v1/map/scenes/{scene.id}/rgb?bbox=72.80,19.00,72.85,19.05")
    assert resp_aoi.status_code in (400, 404)
    data_aoi = resp_aoi.json()
    msg_aoi = data_aoi.get("error", {}).get("message", "") or data_aoi.get("detail", "")
    assert "does not intersect satellite scene extent" in msg_aoi


