import pytest
from pathlib import Path
from datetime import datetime, timezone
from starlette.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.services.storage_service import LocalStorageService, StoragePathTraversalError
from app.services.storage.reset_service import StorageResetService, format_bytes
from app.db.models.water_body import WaterBody
from app.db.models.satellite_scene import SatelliteScene
from app.db.models.satellite_asset import SatelliteAsset
from app.db.models.analysis_run import AnalysisRun
from app.db.models.cache_entry import CacheEntry


@pytest.fixture
def isolated_storage(tmp_path: Path):
    """Provides a fresh isolated storage directory with standard subfolders."""
    storage_root = tmp_path / "data"
    storage_root.mkdir(parents=True, exist_ok=True)
    svc = LocalStorageService(base_dir=storage_root)
    return svc


@pytest.fixture
def reset_service(isolated_storage):
    """Provides an isolated StorageResetService."""
    return StorageResetService(storage=isolated_storage)


def test_format_bytes():
    assert format_bytes(500) == "500 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1024 * 1024) == "1.00 MB"
    assert format_bytes(1024 * 1024 * 1024) == "1.00 GB"


def test_storage_status_empty(reset_service, db_session: Session):
    status = reset_service.collect_storage_status(db_session)
    assert status.database["status"] == "ok"
    assert status.database_counts.water_bodies == 0
    assert status.database_counts.satellite_scenes == 0
    assert status.database_counts.satellite_assets == 0
    assert status.database_counts.analysis_runs == 0
    assert status.database_counts.cache_entries == 0
    assert status.local_storage.satellite_data_bytes == 0
    assert status.local_storage.processed_data_bytes == 0
    assert status.local_storage.cache_bytes == 0
    assert status.orphans.orphan_scene_directories_count == 0


def test_storage_status_populated_and_orphans(reset_service, db_session: Session):
    # 1. Insert DB records
    wb = WaterBody(
        name="Test Lake",
        normalized_name="test lake",
        country="India",
        source="manual",
        source_id="test-1",
        is_active=True,
    )
    db_session.add(wb)

    scene = SatelliteScene(
        provider="copernicus",
        collection="sentinel-2-l2a",
        external_scene_id="S2A_TEST_001",
        sensing_start=datetime.now(timezone.utc),
        status="downloaded",
    )
    db_session.add(scene)
    db_session.commit()

    asset = SatelliteAsset(
        scene_id=scene.id,
        asset_key="B02",
        local_path="scenes/S2A_TEST_001/B02.tif",
        file_size_bytes=1000,
        status="available",
    )
    db_session.add(asset)

    run = AnalysisRun(
        water_body_id=wb.id,
        scene_id=scene.id,
        analysis_type="water_detection",
        status="completed",
    )
    db_session.add(run)

    cache = CacheEntry(
        cache_key="test-cache-key",
        cache_type="stac_search",
        source="stac",
        file_size_bytes=256,
        status="valid",
    )
    db_session.add(cache)
    db_session.commit()

    # 2. Create matching scene folder and an orphan scene folder on disk
    scene_dir = reset_service.storage.base_dir / "scenes" / "S2A_TEST_001"
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "B02.tif").write_bytes(b"x" * 1000)

    orphan_dir = reset_service.storage.base_dir / "scenes" / "S2B_ORPHAN_999"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "dummy.tif").write_bytes(b"y" * 500)

    # 3. Check status
    status = reset_service.collect_storage_status(db_session)
    assert status.database_counts.water_bodies == 1
    assert status.database_counts.satellite_scenes == 1
    assert status.database_counts.satellite_assets == 1
    assert status.database_counts.analysis_runs == 1
    assert status.database_counts.cache_entries == 1
    assert status.local_storage.satellite_data_bytes == 1500
    assert status.orphans.orphan_scene_directories_count == 1
    assert "S2B_ORPHAN_999" in status.orphans.orphan_scene_directories


def test_clear_cache(reset_service, db_session: Session):
    cache = CacheEntry(
        cache_key="search-key-1",
        cache_type="osm_search",
        status="valid",
    )
    db_session.add(cache)
    db_session.commit()

    # Put a cache file in data/cache/
    cache_file = reset_service.storage.base_dir / "cache" / "query1" / "result.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(b'{"results": []}')

    # Clear cache
    res = reset_service.clear_cache(db_session)
    assert res.success is True
    assert res.database.cache_entries_deleted == 1
    assert res.filesystem.files_deleted == 1
    assert not cache_file.exists()

    # Check database table is empty
    count = db_session.execute(select(func.count()).select_from(CacheEntry)).scalar()
    assert count == 0


def test_clear_processed(reset_service, db_session: Session):
    wb = WaterBody(name="L1", normalized_name="l1", source="m", source_id="s1")
    scene = SatelliteScene(
        provider="p", collection="c", external_scene_id="s1", sensing_start=datetime.now(timezone.utc)
    )
    db_session.add_all([wb, scene])
    db_session.commit()

    run = AnalysisRun(water_body_id=wb.id, scene_id=scene.id, analysis_type="cloud")
    db_session.add(run)
    db_session.commit()

    proc_file = reset_service.storage.base_dir / "processed" / "run_abc" / "mask.png"
    proc_file.parent.mkdir(parents=True, exist_ok=True)
    proc_file.write_bytes(b"PNG_DATA")

    res = reset_service.clear_processed_data(db_session)
    assert res.success is True
    assert res.database.analysis_runs_deleted == 1
    assert res.filesystem.files_deleted == 1
    assert not proc_file.exists()

    count = db_session.execute(select(func.count()).select_from(AnalysisRun)).scalar()
    assert count == 0


def test_clear_satellite(reset_service, db_session: Session):
    scene = SatelliteScene(
        provider="p", collection="c", external_scene_id="s2", sensing_start=datetime.now(timezone.utc)
    )
    db_session.add(scene)
    db_session.commit()

    asset = SatelliteAsset(scene_id=scene.id, asset_key="B04")
    db_session.add(asset)
    db_session.commit()

    scene_file = reset_service.storage.base_dir / "scenes" / "s2" / "B04.tif"
    scene_file.parent.mkdir(parents=True, exist_ok=True)
    scene_file.write_bytes(b"TIFF_DATA")

    res = reset_service.clear_satellite_data(db_session)
    assert res.success is True
    assert res.database.scenes_deleted == 1
    assert res.database.assets_deleted == 1
    assert res.filesystem.files_deleted == 1
    assert not scene_file.exists()


def test_reset_all_data(reset_service, db_session: Session):
    # Populate everything
    wb = WaterBody(name="Lake Reset", normalized_name="lake reset", source="m", source_id="r1")
    scene = SatelliteScene(provider="p", collection="c", external_scene_id="sr1", sensing_start=datetime.now(timezone.utc))
    db_session.add_all([wb, scene])
    db_session.commit()

    asset = SatelliteAsset(scene_id=scene.id, asset_key="B02")
    run = AnalysisRun(water_body_id=wb.id, scene_id=scene.id, analysis_type="water")
    cache = CacheEntry(cache_key="ck", cache_type="ct")
    db_session.add_all([asset, run, cache])
    db_session.commit()

    # Create files in multiple subdirs
    (reset_service.storage.base_dir / "scenes" / "sr1").mkdir(parents=True, exist_ok=True)
    (reset_service.storage.base_dir / "scenes" / "sr1" / "B02.tif").write_bytes(b"TIFF")
    (reset_service.storage.base_dir / "processed" / "pr1").mkdir(parents=True, exist_ok=True)
    (reset_service.storage.base_dir / "processed" / "pr1" / "water.png").write_bytes(b"PNG")
    (reset_service.storage.base_dir / "cache" / "c1").mkdir(parents=True, exist_ok=True)
    (reset_service.storage.base_dir / "cache" / "c1" / "c.json").write_bytes(b"JSON")

    res = reset_service.reset_all_data(db_session)
    assert res.success is True
    assert res.database.water_bodies_deleted == 1
    assert res.database.scenes_deleted == 1
    assert res.database.assets_deleted == 1
    assert res.database.analysis_runs_deleted == 1
    assert res.database.cache_entries_deleted == 1
    assert res.filesystem.files_deleted == 3

    # Verify zero in DB
    status = reset_service.collect_storage_status(db_session)
    assert status.database_counts.water_bodies == 0
    assert status.database_counts.satellite_scenes == 0
    assert status.database_counts.satellite_assets == 0
    assert status.database_counts.analysis_runs == 0
    assert status.database_counts.cache_entries == 0
    assert status.local_storage.satellite_data_bytes == 0
    assert status.local_storage.processed_data_bytes == 0
    assert status.local_storage.cache_bytes == 0


def test_idempotent_reset(reset_service, db_session: Session):
    # Call reset when already empty
    res1 = reset_service.reset_all_data(db_session)
    assert res1.success is True
    assert res1.database.water_bodies_deleted == 0
    assert res1.filesystem.files_deleted == 0

    # Call reset a second time
    res2 = reset_service.reset_all_data(db_session)
    assert res2.success is True
    assert res2.database.water_bodies_deleted == 0
    assert res2.filesystem.files_deleted == 0


def test_missing_directories_handled(reset_service, db_session: Session):
    # Remove scenes directory completely
    scenes_path = reset_service.storage.base_dir / "scenes"
    if scenes_path.exists():
        import shutil
        shutil.rmtree(scenes_path)

    # Calling clear_satellite should not crash
    res = reset_service.clear_satellite_data(db_session)
    assert res.success is True
    assert res.filesystem.files_deleted == 0


def test_security_path_traversal_protection(reset_service):
    # Attempting to clear protected or traversing paths should be blocked
    with pytest.raises(ValueError):
        reset_service._safe_clear_directory("database")

    with pytest.raises(ValueError):
        reset_service._safe_clear_directory("")

    with pytest.raises(StoragePathTraversalError):
        reset_service._safe_clear_directory("../../../")


def test_database_integrity_and_usability_after_reset(reset_service, db_session: Session):
    # Perform full reset
    reset_service.reset_all_data(db_session)

    # Tables still exist and queries succeed
    wbs = db_session.execute(select(WaterBody)).scalars().all()
    assert len(wbs) == 0

    # Can insert a fresh water body normally
    new_wb = WaterBody(
        name="Fresh Lake",
        normalized_name="fresh lake",
        source="manual",
        source_id="fresh-1",
    )
    db_session.add(new_wb)
    db_session.commit()
    assert new_wb.id is not None

    refreshed_wb = db_session.execute(select(WaterBody).where(WaterBody.id == new_wb.id)).scalar_one()
    assert refreshed_wb.name == "Fresh Lake"


# ─── API Endpoint Tests ─────────────────────────────────────────────────────────

def test_api_storage_endpoints(client: TestClient, reset_service):
    from unittest.mock import patch
    with patch("app.api.v1.storage.reset_service", reset_service):
        # GET /api/v1/storage/status
        res = client.get("/api/v1/storage/status")
        assert res.status_code == 200
        data = res.json()
        assert "database_counts" in data
        assert "local_storage" in data
        assert "orphans" in data

        # POST /api/v1/storage/clear/cache
        res = client.post("/api/v1/storage/clear/cache")
        assert res.status_code == 200
        assert res.json()["success"] is True

        # POST /api/v1/storage/clear/processed
        res = client.post("/api/v1/storage/clear/processed")
        assert res.status_code == 200
        assert res.json()["success"] is True

        # POST /api/v1/storage/clear/satellite
        res = client.post("/api/v1/storage/clear/satellite")
        assert res.status_code == 200
        assert res.json()["success"] is True

        # POST /api/v1/storage/reset
        res = client.post("/api/v1/storage/reset")
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert "database" in res.json()
        assert "filesystem" in res.json()
