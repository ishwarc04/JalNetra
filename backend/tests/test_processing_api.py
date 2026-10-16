"""
Integration tests for Processing API endpoints (Phase 5).
"""
import pytest
from pathlib import Path
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.satellite_scene import SatelliteScene
from app.db.models.satellite_asset import SatelliteAsset
from tests.test_processing_service import (
    create_synthetic_scl_raster,
    create_synthetic_band_raster,
)


def test_processing_api_endpoints(client: TestClient, db_session: Session, tmp_path: Path, monkeypatch):
    """Verifies POST /scenes/{id}, GET /scenes/{id}, and mask overlay endpoints."""
    import app.services.processing.service as proc_module

    # Monkeypatch data_dir in processing service
    monkeypatch.setattr(proc_module.settings, "DATA_DIR", str(tmp_path))

    scene_id = "api-proc-test-scene"
    scene_dir = tmp_path / "scenes" / scene_id / "assets"
    
    scene = SatelliteScene(
        id=scene_id,
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2A_API_PROC_TEST",
        sensing_start=datetime.now(timezone.utc),
        status="downloaded",
    )
    db_session.add(scene)

    scl_file = scene_dir / "SCL.tif"
    b03_file = scene_dir / "B03.tif"
    b08_file = scene_dir / "B08.tif"

    create_synthetic_scl_raster(scl_file)
    create_synthetic_band_raster(b03_file, val_map={"water": 1800, "land": 500, "shadow": 800})
    create_synthetic_band_raster(b08_file, val_map={"water": 200, "land": 2500, "shadow": 300})

    for key, fpath in [("SCL", scl_file), ("B03", b03_file), ("B08", b08_file)]:
        asset = SatelliteAsset(
            scene_id=scene_id,
            asset_key=key,
            asset_type="image/tiff",
            local_path=f"scenes/{scene_id}/assets/{key}.tif",
            status="downloaded",
            file_size_bytes=fpath.stat().st_size,
        )
        db_session.add(asset)
    db_session.commit()

    # 1. GET status before processing
    stat_resp = client.get(f"/api/v1/processing/scenes/{scene_id}")
    assert stat_resp.status_code == 200
    assert stat_resp.json()["status"] == "unprocessed"

    # 2. POST run processing
    post_resp = client.post(f"/api/v1/processing/scenes/{scene_id}")
    assert post_resp.status_code == 200
    post_data = post_resp.json()
    assert post_data["status"] == "ready"
    assert post_data["cloud_mask_available"] is True
    assert post_data["water_mask_available"] is True
    assert post_data["water_detection"]["water_pixels"] == 100

    # 3. GET cloud mask visualization
    cm_vis = client.get(f"/api/v1/processing/scenes/{scene_id}/cloud-mask")
    assert cm_vis.status_code == 200
    assert cm_vis.json()["crs"] == "EPSG:4326"

    # 4. GET cloud mask image
    cm_img = client.get(f"/api/v1/processing/scenes/{scene_id}/cloud-mask/image")
    assert cm_img.status_code == 200
    assert cm_img.headers["content-type"] == "image/png"
    assert len(cm_img.content) > 0

    # 5. GET water mask visualization
    wm_vis = client.get(f"/api/v1/processing/scenes/{scene_id}/water-mask")
    assert wm_vis.status_code == 200
    assert wm_vis.json()["crs"] == "EPSG:4326"

    # 6. GET water mask image
    wm_img = client.get(f"/api/v1/processing/scenes/{scene_id}/water-mask/image")
    assert wm_img.status_code == 200
    assert wm_img.headers["content-type"] == "image/png"
    assert len(wm_img.content) > 0

    # 7. GET cloud mask & water mask with bbox parameter
    bbox_str = "85.1,19.4,85.3,19.6"
    cm_bbox = client.get(f"/api/v1/processing/scenes/{scene_id}/cloud-mask?bbox={bbox_str}")
    assert cm_bbox.status_code == 200
    assert cm_bbox.json()["bounds"]["west"] == pytest.approx(85.1, abs=0.05)

    cm_bbox_img = client.get(f"/api/v1/processing/scenes/{scene_id}/cloud-mask/image?bbox={bbox_str}")
    assert cm_bbox_img.status_code == 200
    assert cm_bbox_img.headers["content-type"] == "image/png"

    wm_bbox = client.get(f"/api/v1/processing/scenes/{scene_id}/water-mask?bbox={bbox_str}")
    assert wm_bbox.status_code == 200
    assert wm_bbox.json()["bounds"]["west"] == pytest.approx(85.1, abs=0.05)

    wm_bbox_img = client.get(f"/api/v1/processing/scenes/{scene_id}/water-mask/image?bbox={bbox_str}")
    assert wm_bbox_img.status_code == 200
    assert wm_bbox_img.headers["content-type"] == "image/png"


def test_processing_api_security_path_traversal(client: TestClient):
    """Verifies that arbitrary path traversal attempts return 404/422."""
    resp = client.get("/api/v1/processing/scenes/../../etc/passwd/water-mask/image")
    assert resp.status_code in [404, 422]
