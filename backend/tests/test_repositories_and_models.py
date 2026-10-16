from datetime import datetime, timezone
import pytest
from app.db.models.water_body import WaterBody
from app.db.models.satellite_scene import SatelliteScene
from app.db.models.satellite_asset import SatelliteAsset
from app.db.models.analysis_run import AnalysisRun
from app.db.models.cache_entry import CacheEntry
from app.db.repositories.water_body_repository import WaterBodyRepository
from app.db.repositories.satellite_scene_repository import SatelliteSceneRepository
from app.db.repositories.satellite_asset_repository import SatelliteAssetRepository
from app.db.repositories.analysis_run_repository import AnalysisRunRepository
from app.db.repositories.cache_repository import CacheRepository
from app.schemas.water_body import WaterBodyCreate, WaterBodyUpdate
from app.schemas.satellite_scene import SatelliteSceneCreate
from app.schemas.satellite_asset import SatelliteAssetCreate
from app.schemas.analysis_run import AnalysisRunCreate
from app.schemas.cache import CacheEntryCreate
from app.services.water_body_service import WaterBodyService, WaterBodyConflictError


def test_water_body_repository_crud(db_session):
    repo = WaterBodyRepository(db_session)
    create_dto = WaterBodyCreate(
        name="Lake Pichola",
        country="India",
        state_province="Rajasthan",
        district="Udaipur",
        city="Udaipur",
        source="osm",
        source_id="osm-12345",
        water_body_type="lake",
        min_lat=24.56,
        min_lon=73.66,
        max_lat=24.59,
        max_lon=73.69,
        centroid_lat=24.575,
        centroid_lon=73.675,
        area_sq_km=6.96,
        geometry_geojson='{"type":"Polygon","coordinates":[[[73.66,24.56],[73.69,24.56],[73.69,24.59],[73.66,24.59],[73.66,24.56]]]}',
    )
    wb = repo.create(create_dto)
    assert wb.id is not None
    assert wb.name == "Lake Pichola"
    assert wb.normalized_name == "lake pichola"
    assert wb.geometry_hash is not None
    assert wb.is_active is True

    # Get by ID
    fetched = repo.get_by_id(wb.id)
    assert fetched is not None
    assert fetched.name == "Lake Pichola"

    # Update
    update_dto = WaterBodyUpdate(description="Historic artificial freshwater lake")
    updated = repo.update(fetched, update_dto)
    assert updated.description == "Historic artificial freshwater lake"

    # Deactivate
    deactivated = repo.deactivate(updated)
    assert deactivated.is_active is False

    # List
    items, total = repo.list_water_bodies(country="India", is_active=False)
    assert total >= 1
    assert any(item.id == wb.id for item in items)


def test_water_body_service_duplicate_source_id(db_session):
    service = WaterBodyService(db_session)
    dto = WaterBodyCreate(
        name="Chilika Lake",
        source="hydrolakes",
        source_id="hl-9999",
    )
    wb1 = service.create_water_body(dto)
    assert wb1.id is not None

    # Duplicate should raise WaterBodyConflictError
    with pytest.raises(WaterBodyConflictError):
        service.create_water_body(dto)


def test_relationships(db_session):
    wb_repo = WaterBodyRepository(db_session)
    scene_repo = SatelliteSceneRepository(db_session)
    asset_repo = SatelliteAssetRepository(db_session)
    run_repo = AnalysisRunRepository(db_session)

    # 1. Create Water Body
    wb = wb_repo.create(WaterBodyCreate(name="Vembanad Lake", source="manual"))

    # 2. Create Satellite Scene
    scene = scene_repo.create(
        SatelliteSceneCreate(
            provider="copernicus",
            collection="sentinel-2-l2a",
            external_scene_id="S2A_MSIL2A_20261011_TEST",
            sensing_start=datetime.now(timezone.utc),
            cloud_cover_percent=4.2,
            status="discovered",
        )
    )

    # 3. Create Satellite Asset
    asset = asset_repo.create(
        SatelliteAssetCreate(
            scene_id=scene.id,
            asset_key="B04",
            asset_type="raster_band",
            remote_url="https://example.com/b04.jp2",
            status="remote",
        )
    )

    # 4. Create Analysis Run
    run = run_repo.create(
        AnalysisRunCreate(
            water_body_id=wb.id,
            scene_id=scene.id,
            analysis_type="ndwi_water_mask",
            status="queued",
        )
    )

    # Verify relationships
    assert len(scene.assets) == 1
    assert scene.assets[0].asset_key == "B04"
    assert asset.scene.external_scene_id == "S2A_MSIL2A_20261011_TEST"

    assert len(wb.analysis_runs) == 1
    assert wb.analysis_runs[0].analysis_type == "ndwi_water_mask"
    assert len(scene.analysis_runs) == 1
    assert scene.analysis_runs[0].water_body.name == "Vembanad Lake"


def test_cache_repository(db_session):
    repo = CacheRepository(db_session)
    entry = repo.create(
        CacheEntryCreate(
            cache_key="stac-query-lake-pichola",
            cache_type="stac_search_result",
            source="copernicus",
            file_size_bytes=1024,
            sha256="abcdef123456",
        )
    )
    assert entry.id is not None
    fetched = repo.get_by_key("stac-query-lake-pichola")
    assert fetched is not None
    assert fetched.file_size_bytes == 1024

    deleted = repo.delete_by_key("stac-query-lake-pichola")
    assert deleted is True
    assert repo.get_by_key("stac-query-lake-pichola") is None
