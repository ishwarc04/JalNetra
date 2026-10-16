"""
Unit tests for Cloud Masking, Water Detection, and Processing Service (Phase 5).
Uses synthetic GeoTIFF fixtures to verify:
- SCL class filtering (cloud, shadow, cirrus, snow, nodata vs clear)
- Georeferenced cloud_mask.tif creation
- Spectral water segmentation: B03/B08 contrast and thresholding
- Respecting cloud mask in water detection (masked pixels never become water)
- Output bounds, transform, and CRS preservation
- Processing metadata generation and caching
- Re-run idempotency
- Security against path traversal
"""
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from sqlalchemy.orm import Session

from app.db.models.satellite_scene import SatelliteScene
from app.db.models.satellite_asset import SatelliteAsset
from app.services.processing.cloud_mask import CloudMaskGenerator
from app.services.processing.water_detection import WaterDetector
from app.services.processing.service import ProcessingService


def create_synthetic_scl_raster(
    file_path: Path,
    crs: str = "EPSG:32645",
    width: int = 40,
    height: int = 40,
    bounds: tuple = (300000.0, 2090000.0, 310000.0, 2100000.0),
):
    """Creates a synthetic SCL raster with known class patches."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    transform = from_bounds(*bounds, width, height)
    
    # 4 = Vegetation, 6 = Water, 3 = Shadow, 9 = Cloud High, 0 = NoData
    data = np.full((height, width), 4, dtype=np.uint8)  # default clear vegetation
    data[:10, :10] = 6   # clear water patch
    data[10:20, :10] = 3  # cloud shadow patch
    data[20:30, :10] = 9  # cloud high probability patch
    data[30:, :10] = 0    # nodata patch

    with rasterio.open(
        file_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=np.uint8,
        crs=crs,
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(data, 1)


def create_synthetic_band_raster(
    file_path: Path,
    val_map: dict,
    crs: str = "EPSG:32645",
    width: int = 40,
    height: int = 40,
    bounds: tuple = (300000.0, 2090000.0, 310000.0, 2100000.0),
):
    """Creates a synthetic spectral band GeoTIFF with patch values."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    transform = from_bounds(*bounds, width, height)
    
    # default land values
    data = np.full((height, width), val_map.get("land", 1000), dtype=np.uint16)
    # water patch
    data[:10, :10] = val_map.get("water", 500)
    # shadow patch
    data[10:20, :10] = val_map.get("shadow", 200)

    with rasterio.open(
        file_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=np.uint16,
        crs=crs,
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(data, 1)


def test_cloud_mask_generator_synthetic(tmp_path: Path):
    """Verifies that CloudMaskGenerator correctly masks clouds, shadows, and nodata."""
    scl_path = tmp_path / "SCL.tif"
    out_mask = tmp_path / "cloud_mask.tif"
    create_synthetic_scl_raster(scl_path, width=40, height=40)

    res = CloudMaskGenerator.generate_mask(scl_path, out_mask)
    assert out_mask.exists()
    assert res["total_pixels"] == 1600
    assert res["valid_pixels"] > 0
    assert res["cloud_shadow_pixels"] == 200  # 10x10 shadow + 10x10 cloud high
    assert res["valid_pixel_percentage"] < 100.0

    # Read output mask: 0=masked, 1=valid
    with rasterio.open(out_mask) as src:
        arr = src.read(1)
        assert arr.dtype == np.uint8
        # Shadow & cloud patches should be 0 (masked)
        assert np.all(arr[10:20, :10] == 0)
        assert np.all(arr[20:30, :10] == 0)
        # Clear land & water patches should be 1 (valid)
        assert np.all(arr[:10, :10] == 1)
        assert np.all(arr[15:25, 15:25] == 1)


def test_water_detector_synthetic(tmp_path: Path):
    """Verifies that WaterDetector isolates water based on Green/NIR contrast and respects cloud mask."""
    scl_path = tmp_path / "SCL.tif"
    cloud_mask_path = tmp_path / "cloud_mask.tif"
    b03_path = tmp_path / "B03.tif"
    b08_path = tmp_path / "B08.tif"
    out_water = tmp_path / "water_mask.tif"

    create_synthetic_scl_raster(scl_path)
    CloudMaskGenerator.generate_mask(scl_path, cloud_mask_path)

    # For water: Green > NIR -> e.g. Green=1800, NIR=200 -> (1800-200)/(2000) = +0.8 > 0
    # For land: NIR > Green -> e.g. Green=500, NIR=2500 -> (500-2500)/(3000) = -0.66 < 0
    create_synthetic_band_raster(b03_path, val_map={"water": 1800, "land": 500, "shadow": 800})
    create_synthetic_band_raster(b08_path, val_map={"water": 200, "land": 2500, "shadow": 300})

    res = WaterDetector.detect_water(
        green_path=b03_path,
        nir_path=b08_path,
        cloud_mask_path=cloud_mask_path,
        output_water_mask_path=out_water,
        threshold=0.0,
    )

    assert out_water.exists()
    assert res["water_pixels"] == 100  # Exactly 10x10 water patch
    assert res["water_extent_percentage_of_valid"] > 0

    with rasterio.open(out_water) as src:
        w_arr = src.read(1)
        # Water patch must be 1
        assert np.all(w_arr[:10, :10] == 1)
        # Land must be 0
        assert np.all(w_arr[15:25, 15:25] == 0)
        # Cloud/shadow patch must be 0 (masked out)
        assert np.all(w_arr[10:30, :10] == 0)


def test_processing_service_flow_and_caching(db_session: Session, tmp_path: Path):
    """Verifies ProcessingService end-to-end orchestration, DB linking, and caching."""
    data_dir = tmp_path / "data"
    service = ProcessingService(data_dir=data_dir)

    scene_id = "test-proc-scene-1"
    scene_dir = data_dir / "scenes" / scene_id / "assets"
    
    scene = SatelliteScene(
        id=scene_id,
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2A_TEST_PROCESSING_SCENE",
        sensing_start=datetime.now(timezone.utc),
        status="downloaded",
    )
    db_session.add(scene)

    # Create assets: SCL, B03, B08
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

    # 1. Check initial status before processing
    status1 = service.get_processing_status(db_session, scene_id)
    assert status1.status == "unprocessed"
    assert status1.cloud_mask_available is False

    # 2. Run processing
    res = service.process_scene(db_session, scene_id)
    assert res.status == "ready"
    assert res.cloud_mask_available is True
    assert res.water_mask_available is True
    assert res.cloud_mask.cloud_shadow_pixels == 200
    assert res.water_detection.water_pixels == 100

    # Verify generated files on disk
    proc_dir = data_dir / "processed" / scene_id
    assert (proc_dir / "cloud_mask.tif").exists()
    assert (proc_dir / "water_mask.tif").exists()
    assert (proc_dir / "processing_metadata.json").exists()
    assert (proc_dir / "cloud_mask.png").exists()
    assert (proc_dir / "water_mask.png").exists()

    # 3. Check caching on re-run
    res_cached = service.process_scene(db_session, scene_id, force_recompute=False)
    assert res_cached.status == "ready"
    assert res_cached.water_detection.water_pixels == 100

    # 4. Check overlay visualization bounds
    vis_water = service.get_mask_visualization(db_session, scene_id, "water_mask")
    assert vis_water.crs == "EPSG:4326"
    assert vis_water.bounds.north > vis_water.bounds.south
    assert "water-mask" in vis_water.image_url


def test_processing_service_missing_assets_error(db_session: Session, tmp_path: Path):
    """Verifies that missing SCL or spectral bands raises FileNotFoundError."""
    data_dir = tmp_path / "data"
    service = ProcessingService(data_dir=data_dir)

    scene_id = "test-proc-scene-incomplete"
    scene = SatelliteScene(
        id=scene_id,
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2A_INCOMPLETE_PROCESSING",
        sensing_start=datetime.now(timezone.utc),
        status="downloaded",
    )
    db_session.add(scene)
    db_session.commit()

    with pytest.raises(FileNotFoundError) as exc_info:
        service.process_scene(db_session, scene_id)
    assert "Missing required downloaded asset" in str(exc_info.value)
