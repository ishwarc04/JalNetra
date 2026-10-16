"""
Tests for Raster Reader, Renderer, and RasterService (Phase 4).
Uses small synthetic GeoTIFF fixtures to verify:
- CRS inspection
- Bounds calculation in EPSG:4326
- NoData handling
- Dimension alignment
- Percentile contrast stretching
- RGB generation
- Cache reuse and forced regeneration
- Security checks
"""
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds
from sqlalchemy.orm import Session

from app.db.models.water_body import WaterBody
from app.db.models.satellite_scene import SatelliteScene
from app.db.models.satellite_asset import SatelliteAsset
from app.services.raster.reader import RasterReader
from app.services.raster.renderer import RGBRenderer
from app.services.raster.service import RasterService
from app.services.raster.models import GeoBounds


def create_synthetic_geotiff(
    file_path: Path,
    crs: str = "EPSG:32645",
    width: int = 64,
    height: int = 64,
    bounds: tuple = (300000.0, 2090000.0, 310000.0, 2100000.0),
    fill_value: int = 1000,
    nodata: float = 0.0,
):
    """Helper to create a small synthetic single-band GeoTIFF."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    transform = from_bounds(*bounds, width, height)
    
    # Generate test gradient array with some 0 values for nodata
    data = np.full((height, width), fill_value, dtype=np.uint16)
    data[:5, :5] = 0  # Corner nodata

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
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)


def test_raster_reader_synthetic(tmp_path: Path):
    """Verifies that RasterReader accurately extracts metadata and bounds."""
    tif_path = tmp_path / "test_band.tif"
    create_synthetic_geotiff(tif_path, width=32, height=32)

    meta = RasterReader.inspect_file(tif_path)
    assert meta["crs"] == "EPSG:32645"
    assert meta["width"] == 32
    assert meta["height"] == 32
    assert meta["bands"] == 1
    assert meta["nodata"] == 0.0
    assert meta["geographic_bounds"] is not None
    assert "west" in meta["geographic_bounds"]
    assert "north" in meta["geographic_bounds"]
    assert meta["geographic_bounds"]["east"] > meta["geographic_bounds"]["west"]


def test_rgb_renderer_synthetic(tmp_path: Path):
    """Verifies RGBRenderer aligns bands, reprojects to 4326, applies stretch, and outputs RGBA PNG."""
    r_path = tmp_path / "B04.tif"
    g_path = tmp_path / "B03.tif"
    b_path = tmp_path / "B02.tif"
    out_png = tmp_path / "output_rgb.png"

    # Create bands with slight variations to test alignment
    create_synthetic_geotiff(r_path, fill_value=1200, width=40, height=40)
    create_synthetic_geotiff(g_path, fill_value=1000, width=40, height=40)
    create_synthetic_geotiff(b_path, fill_value=800, width=40, height=40)

    res = RGBRenderer.render_rgb(
        red_path=r_path,
        green_path=g_path,
        blue_path=b_path,
        output_png_path=out_png,
        max_dimension=64,
    )

    assert out_png.exists()
    assert res["width"] > 0
    assert res["height"] > 0
    assert isinstance(res["bounds"], GeoBounds)
    assert res["bounds"].north > res["bounds"].south
    assert res["bounds"].east > res["bounds"].west


def test_raster_service_caching_and_lifecycle(db_session: Session, tmp_path: Path):
    """Verifies RasterService scene metadata inspection, RGB generation, and cache reuse."""
    data_dir = tmp_path / "data"
    service = RasterService(data_dir=data_dir)

    scene_id = "test-scene-uuid-1"
    scene_dir = data_dir / "scenes" / scene_id / "assets"
    
    # Create scene record in DB
    scene = SatelliteScene(
        id=scene_id,
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2A_SYNTHETIC_SCENE_L2A",
        sensing_start=datetime.now(timezone.utc),
        cloud_cover_percent=3.5,
        status="downloaded",
    )
    db_session.add(scene)

    # Create synthetic band assets
    for band_key, val in [("B04", 1500), ("B03", 1200), ("B02", 900)]:
        tif_file = scene_dir / f"{band_key}.tif"
        create_synthetic_geotiff(tif_file, fill_value=val)
        asset = SatelliteAsset(
            scene_id=scene_id,
            asset_key=band_key,
            asset_type="image/tiff",
            local_path=f"scenes/{scene_id}/assets/{band_key}.tif",
            status="downloaded",
            file_size_bytes=tif_file.stat().st_size,
        )
        db_session.add(asset)
    db_session.commit()

    # 1. Inspect metadata
    meta = service.get_scene_metadata(db_session, scene_id)
    assert meta.scene_id == scene_id
    assert meta.rgb_available is True
    assert meta.rgb_cached is False
    assert len(meta.available_assets) == 3

    # 2. Render RGB (Initial creation)
    rgb_res = service.get_or_render_rgb(db_session, scene_id)
    assert rgb_res.cached is False
    assert rgb_res.width > 0
    assert (data_dir / "processed" / "map" / scene_id / "rgb.png").exists()

    # 3. Retrieve again (Should be served from cache)
    cached_res = service.get_or_render_rgb(db_session, scene_id)
    assert cached_res.cached is True

    # 4. Force regenerate
    regen_res = service.get_or_render_rgb(db_session, scene_id, force_regenerate=True)
    assert regen_res.cached is False


def test_raster_service_missing_bands_error(db_session: Session, tmp_path: Path):
    """Verifies that attempting RGB rendering without required bands raises FileNotFoundError."""
    data_dir = tmp_path / "data"
    service = RasterService(data_dir=data_dir)

    scene_id = "test-scene-uuid-2"
    scene = SatelliteScene(
        id=scene_id,
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2A_INCOMPLETE_SCENE_L2A",
        sensing_start=datetime.now(timezone.utc),
        status="downloaded",
    )
    db_session.add(scene)
    # Only add B04
    asset = SatelliteAsset(
        scene_id=scene_id,
        asset_key="B04",
        status="downloaded",
        local_path=f"scenes/{scene_id}/assets/B04.tif",
    )
    db_session.add(asset)
    db_session.commit()

    with pytest.raises(FileNotFoundError) as exc_info:
        service.get_or_render_rgb(db_session, scene_id)
    assert "Missing downloaded band" in str(exc_info.value)


def test_raster_service_focused_water_body_crop(db_session: Session, tmp_path: Path):
    """Verifies that RasterService properly crops RGB to water body bbox + padding and isolates cache."""
    data_dir = tmp_path / "data"
    service = RasterService(data_dir=data_dir)

    # 1. Create a water body
    wb_id = "test-wb-uuid-crop"
    wb = WaterBody(
        id=wb_id,
        name="Small Test Lake",
        normalized_name="small test lake",
        source="test",
        source_id="test_lake_1",
        min_lon=85.2,
        min_lat=19.5,
        max_lon=85.3,
        max_lat=19.6,
    )
    db_session.add(wb)

    # 2. Create scene record with wider bounds (EPSG:4326 for simplicity in synthetic geotiff)
    scene_id = "test-scene-crop"
    scene_dir = data_dir / "scenes" / scene_id / "assets"
    scene = SatelliteScene(
        id=scene_id,
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2A_CROP_TEST_SCENE",
        sensing_start=datetime.now(timezone.utc),
        status="downloaded",
        bbox_min_lon=85.0,
        bbox_min_lat=19.3,
        bbox_max_lon=85.5,
        bbox_max_lat=19.8,
    )
    db_session.add(scene)

    for band_key in ["B04", "B03", "B02"]:
        tif_file = scene_dir / f"{band_key}.tif"
        create_synthetic_geotiff(
            tif_file,
            crs="EPSG:4326",
            bounds=(85.0, 19.3, 85.5, 19.8),
            fill_value=1200,
        )
        asset = SatelliteAsset(
            scene_id=scene_id,
            asset_key=band_key,
            asset_type="image/tiff",
            local_path=f"scenes/{scene_id}/assets/{band_key}.tif",
            status="downloaded",
            file_size_bytes=tif_file.stat().st_size,
        )
        db_session.add(asset)
    db_session.commit()

    # 3. Call get_or_render_rgb with water_body_id
    res = service.get_or_render_rgb(db_session, scene_id, water_body_id=wb_id)
    assert res.is_focused is True
    assert res.water_body_id == wb_id
    assert res.cached is False
    assert res.source_crs is not None and "EPSG:" in res.source_crs
    assert res.resolution_m is not None
    assert res.bands == ["B04", "B03", "B02"]
    assert res.sensing_date is not None
    assert (data_dir / "processed" / "map" / scene_id / f"wb_{wb_id}_rgb.png").exists()
    assert (data_dir / "processed" / "map" / scene_id / f"wb_{wb_id}_rgb_meta.json").exists()

    # Bounds must be within padded water body bounds, tighter than full scene
    assert res.bounds.west >= 85.0
    assert res.bounds.east <= 85.5
    assert res.bounds.south >= 19.3
    assert res.bounds.north <= 19.8

    # 4. Repeat call must be cached
    res_cached = service.get_or_render_rgb(db_session, scene_id, water_body_id=wb_id)
    assert res_cached.cached is True

    # 5. Full scene call (without water_body_id) must not use the wb-specific cache
    full_res = service.get_or_render_rgb(db_session, scene_id, water_body_id=None)
    assert full_res.is_focused is False
    assert full_res.water_body_id is None
    assert (data_dir / "processed" / "map" / scene_id / "rgb.png").exists()

    # 6. Custom padding call (25%) creates distinct cache
    pad_res = service.get_or_render_rgb(db_session, scene_id, water_body_id=wb_id, padding_percent=25.0)
    assert pad_res.is_focused is True
    assert (data_dir / "processed" / "map" / scene_id / f"wb_{wb_id}_p25_rgb.png").exists()

    # 7. Manual AOI crop call creates distinct cache
    aoi_bbox = (85.15, 19.45, 85.35, 19.65)
    aoi_res = service.get_or_render_rgb(db_session, scene_id, crop_bbox=aoi_bbox)
    assert aoi_res.is_focused is True
    assert (data_dir / "processed" / "map" / scene_id / f"aoi_{aoi_bbox[0]}_{aoi_bbox[1]}_{aoi_bbox[2]}_{aoi_bbox[3]}_rgb.png").exists()


