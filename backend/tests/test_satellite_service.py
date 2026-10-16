import json
import pytest
import httpx
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.services.satellite.models import (
    NormalizedScene,
    NormalizedAsset,
)
from app.services.satellite.providers.stac import EarthSearchSTACProvider
from app.services.satellite.ranking import (
    compute_bbox_intersection_ratio,
    rank_and_score_scenes,
)
from app.services.satellite.cache import SatelliteCacheService
from app.services.satellite.service import (
    SatelliteService,
    SatelliteServiceError,
)
from app.services.storage_service import LocalStorageService
from app.db.repositories.water_body_repository import WaterBodyRepository
from app.schemas.water_body import WaterBodyCreate

MOCK_STAC_FEATURE = {
    "type": "Feature",
    "stac_version": "1.0.0",
    "id": "S2A_T45QTB_20240221T045850_L2A",
    "collection": "sentinel-2-c1-l2a",
    "bbox": [84.13, 18.88, 85.19, 19.88],
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [
                [84.13, 18.88],
                [85.19, 18.88],
                [85.19, 19.88],
                [84.13, 19.88],
                [84.13, 18.88],
            ]
        ],
    },
    "properties": {
        "datetime": "2024-02-21T05:03:19.782000Z",
        "eo:cloud_cover": 8.5,
        "processing:level": "L2A",
        "sentinel:product_id": "S2A_MSIL2A_20240221T045850_N0510_R119_T45QTB_20240221T075429",
    },
    "assets": {
        "blue": {
            "href": "https://example.com/B02.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "file:size": 200000000,
        },
        "green": {
            "href": "https://example.com/B03.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "file:size": 200000000,
        },
        "red": {
            "href": "https://example.com/B04.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "file:size": 200000000,
        },
        "nir": {
            "href": "https://example.com/B08.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "file:size": 200000000,
        },
        "swir16": {
            "href": "https://example.com/B11.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "file:size": 100000000,
        },
        "swir22": {
            "href": "https://example.com/B12.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "file:size": 100000000,
        },
        "scl": {
            "href": "https://example.com/SCL.tif",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "roles": ["data"],
            "file:size": 50000000,
        },
        "thumbnail": {
            "href": "https://example.com/thumbnail.jpg",
            "type": "image/jpeg",
            "roles": ["thumbnail"],
            "file:size": 25000,
        },
    },
}


def test_stac_item_normalization():
    provider = EarthSearchSTACProvider()
    scene = provider._normalize_stac_item(MOCK_STAC_FEATURE)

    assert scene is not None
    assert scene.external_scene_id == "S2A_T45QTB_20240221T045850_L2A"
    assert scene.cloud_cover_percent == 8.5
    assert scene.processing_level == "L2A"
    assert scene.provider == "earth_search"

    # Verify canonical mapped asset keys
    assert "B02" in scene.assets
    assert "B03" in scene.assets
    assert "B04" in scene.assets
    assert "B08" in scene.assets
    assert "B11" in scene.assets
    assert "B12" in scene.assets
    assert "SCL" in scene.assets
    assert "thumbnail" in scene.assets

    assert scene.assets["B02"].remote_url == "https://example.com/B02.tif"
    assert scene.assets["B02"].asset_type == "raster_band"
    assert scene.assets["SCL"].asset_type == "mask"
    assert scene.assets["thumbnail"].asset_type == "visual"


def test_scene_ranking():
    s1 = NormalizedScene(
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="scene-low-cloud",
        sensing_start=datetime(2024, 2, 20, tzinfo=timezone.utc),
        cloud_cover_percent=2.0,
        bbox=[85.0, 19.0, 86.0, 20.0],
    )
    s2 = NormalizedScene(
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="scene-high-cloud",
        sensing_start=datetime(2024, 2, 20, tzinfo=timezone.utc),
        cloud_cover_percent=70.0,
        bbox=[85.0, 19.0, 86.0, 20.0],
    )
    s3 = NormalizedScene(
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="scene-recent-moderate-cloud",
        sensing_start=datetime(2024, 2, 25, tzinfo=timezone.utc),
        cloud_cover_percent=5.0,
        bbox=[85.0, 19.0, 86.0, 20.0],
    )

    ranked = rank_and_score_scenes([s1, s2, s3], target_bbox=[85.2, 19.2, 85.8, 19.8])
    assert len(ranked) == 3
    # Low cloud + recent should score highest
    assert ranked[0].score is not None
    assert ranked[0].external_scene_id in ("scene-low-cloud", "scene-recent-moderate-cloud")
    assert ranked[-1].external_scene_id == "scene-high-cloud"


def test_satellite_caching(db_session, tmp_path):
    storage = LocalStorageService(base_dir=tmp_path)
    cache = SatelliteCacheService(db=db_session, storage=storage, default_ttl_seconds=300)

    key = cache.build_cache_key("earth_search", "c1", "wb-123", "2024-01-01", "2024-02-01", 20.0, 10)
    assert key.startswith("stac-scenes:earth_search:c1:wb-123")

    assert cache.get(key) is None

    sample_data = [{"external_scene_id": "test-scene-1", "score": 85.0}]
    cache.set(key, "earth_search", "wb-123", sample_data)

    retrieved = cache.get(key)
    assert retrieved is not None
    assert len(retrieved) == 1
    assert retrieved[0]["external_scene_id"] == "test-scene-1"


@pytest.mark.anyio
async def test_satellite_service_search_and_acquire(db_session, tmp_path):
    storage = LocalStorageService(base_dir=tmp_path)
    wb_repo = WaterBodyRepository(db_session)

    # 1. Create a persistent test water body with bounding box
    wb = wb_repo.create(
        WaterBodyCreate(
            name="Chilika Test Lake",
            source="manual",
            source_id="wb-stac-test",
            min_lat=19.46,
            min_lon=85.09,
            max_lat=19.90,
            max_lon=85.65,
            centroid_lat=19.68,
            centroid_lon=85.25,
            geometry_geojson='{"type":"Polygon","coordinates":[[[85.09,19.46],[85.65,19.46],[85.65,19.90],[85.09,19.90],[85.09,19.46]]]}',
        )
    )

    # 2. Mock provider
    mock_provider = AsyncMock(spec=EarthSearchSTACProvider)
    mock_provider.name = "earth_search"
    mock_provider.collection = "sentinel-2-c1-l2a"

    norm_scene = EarthSearchSTACProvider()._normalize_stac_item(MOCK_STAC_FEATURE)
    assert norm_scene is not None
    mock_provider.search_scenes.return_value = [norm_scene]
    mock_provider.get_scene.return_value = norm_scene

    # Mock chunk streaming for asset downloads
    async def mock_stream(url, chunk_size=65536):
        yield b"MOCK_TIFF_BINARY_DATA_CHUNK_1_"
        yield b"MOCK_TIFF_BINARY_DATA_CHUNK_2"

    mock_provider.stream_asset_bytes.side_effect = mock_stream

    service = SatelliteService(
        db=db_session,
        provider=mock_provider,
        storage=storage,
    )

    # 3. Test Search
    search_resp = await service.search_scenes_for_water_body(
        water_body_id=wb.id,
        max_cloud_cover=20.0,
        limit=5,
    )
    assert len(search_resp.results) == 1
    assert search_resp.results[0].external_scene_id == norm_scene.external_scene_id
    mock_provider.search_scenes.assert_called_once()

    # 4. Test Acquire (Download)
    acquire_resp = await service.acquire_scene_assets(
        external_scene_id=norm_scene.external_scene_id,
        asset_keys=["B02", "B03", "thumbnail"],
    )
    assert acquire_resp.status == "completed"
    assert acquire_resp.downloaded_assets == 3
    assert acquire_resp.failed_assets == 0

    # Verify physical file existence in data/scenes/{scene_id}/assets/
    scene_id = acquire_resp.scene_id
    b02_path = tmp_path / f"scenes/{scene_id}/assets/B02.tif"
    assert b02_path.exists()
    assert b02_path.read_bytes() == b"MOCK_TIFF_BINARY_DATA_CHUNK_1_MOCK_TIFF_BINARY_DATA_CHUNK_2"

    meta_path = tmp_path / f"scenes/{scene_id}/metadata.json"
    assert meta_path.exists()

    # Verify SatelliteAsset records in SQLite
    db_assets = service.asset_repo.list_by_scene_id(scene_id)
    assert len(db_assets) == 3
    b02_rec = next(a for a in db_assets if a.asset_key == "B02")
    assert b02_rec.status == "downloaded"
    assert b02_rec.file_size_bytes == len(b"MOCK_TIFF_BINARY_DATA_CHUNK_1_MOCK_TIFF_BINARY_DATA_CHUNK_2")
    assert b02_rec.sha256 is not None

    # 5. Test Idempotency / Duplicate download avoidance
    mock_provider.stream_asset_bytes.reset_mock()
    second_acquire = await service.acquire_scene_assets(
        external_scene_id=norm_scene.external_scene_id,
        asset_keys=["B02"],
    )
    assert second_acquire.already_present_assets == 1
    assert second_acquire.downloaded_assets == 0
    # Provider stream should not have been called because file and SHA256 match
    assert mock_provider.stream_asset_bytes.call_count == 0


@pytest.mark.anyio
async def test_satellite_service_missing_water_body(db_session, tmp_path):
    service = SatelliteService(db=db_session, storage=LocalStorageService(base_dir=tmp_path))
    with pytest.raises(SatelliteServiceError) as exc_info:
        await service.search_scenes_for_water_body("nonexistent-wb-id")
    assert exc_info.value.code == "WATER_BODY_NOT_FOUND"
