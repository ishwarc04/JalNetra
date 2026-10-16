import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.water_body import WaterBody
from app.db.models.satellite_observation import SatelliteObservation
from app.services.spectral.indicators import (
    TurbidityIndicator,
    ChlorophyllIndicator,
    AlgalActivityIndicator,
    SpectralAnomalyIndicator,
)
from app.services.spectral.cloud_mask import SCLCloudMasker
from app.services.spectral.aoi_processor import WaterBodyAOIProcessor
from app.services.spectral.statistics import SpectralStatistics
from app.services.spectral.service import SpectralAnalysisService, SpectralServiceError


def test_ndti_synthetic_calculation():
    """Verify NDTI = (B04 - B03) / (B04 + B03) with known synthetic arrays."""
    # Red = 3000, Green = 1000 -> (3000 - 1000) / (3000 + 1000) = 2000 / 4000 = 0.5
    b04 = np.array([[3000.0, 1000.0], [500.0, 0.0]], dtype=np.float32)
    b03 = np.array([[1000.0, 1000.0], [1500.0, 0.0]], dtype=np.float32)

    ndti = TurbidityIndicator.calculate(b04, b03)
    assert pytest.approx(ndti[0, 0], 1e-4) == 0.5
    assert pytest.approx(ndti[0, 1], 1e-4) == 0.0  # Equal values -> 0
    assert pytest.approx(ndti[1, 0], 1e-4) == -0.5  # (500 - 1500)/(2000) = -0.5
    assert np.isnan(ndti[1, 1])  # 0/0 division by zero -> NaN safely handled


def test_ndci_synthetic_calculation_and_resampling():
    """Verify NDCI = (B05 - B04) / (B05 + B04) with resolution resampling."""
    # B04 (10m) shape (4, 4), B05 (20m) shape (2, 2)
    b04 = np.full((4, 4), 1000.0, dtype=np.float32)
    b05 = np.full((2, 2), 3000.0, dtype=np.float32)

    ndci = ChlorophyllIndicator.calculate(b04, b05)
    assert ndci.shape == (4, 4)
    # (3000 - 1000) / (3000 + 1000) = 2000 / 4000 = 0.5
    assert pytest.approx(np.nanmean(ndci), 1e-4) == 0.5


def test_fai_synthetic_calculation():
    """Verify FAI with synthetic arrays."""
    # Scale 10000 -> reflectances
    # B04 = 1000 (0.10), B05 = 2000 (0.20), B08 = 3000 (0.30)
    # baseline = 0.10 + (0.30 - 0.10) * 0.2260 = 0.10 + 0.0452 = 0.1452
    # FAI = 0.20 - 0.1452 = 0.0548
    b04 = np.full((4, 4), 1000.0, dtype=np.float32)
    b05 = np.full((4, 4), 2000.0, dtype=np.float32)
    b08 = np.full((4, 4), 3000.0, dtype=np.float32)

    fai = AlgalActivityIndicator.calculate(b04, b05, b08)
    assert pytest.approx(fai[0, 0], 1e-4) == 0.0548


def test_aoi_masking_excludes_surrounding_land():
    """Verify pixels outside the water-body polygon are excluded."""
    # Define a simple polygon in center of bounds (lon 75.0 - 75.1, lat 19.0 - 19.1)
    bounds = (75.0, 19.0, 75.1, 19.1)
    # Center box polygon
    geom_geojson = json.dumps({
        "type": "Polygon",
        "coordinates": [[
            [75.03, 19.03],
            [75.07, 19.03],
            [75.07, 19.07],
            [75.03, 19.07],
            [75.03, 19.03],
        ]]
    })

    shape = (50, 50)
    water_mask, is_exact = WaterBodyAOIProcessor.create_water_mask(geom_geojson, bounds, shape)
    assert is_exact is True
    assert water_mask.shape == shape
    # Center pixels must be True (water), border corners must be False (land)
    assert water_mask[0, 0] is False or water_mask[0, 0] == np.bool_(False)
    assert water_mask[25, 25] is True or water_mask[25, 25] == np.bool_(True)

    # Put extreme high turbid value on border land (pixel 0,0) and clean value on center water (pixel 25,25)
    data = np.zeros(shape, dtype=np.float32)
    data[0, 0] = 999.0  # Land contaminant
    data[25, 25] = 0.10   # Water pixel

    # Compute statistics strictly using water_mask
    stats = SpectralStatistics.calculate(data, water_mask, total_water_pixels=int(np.sum(water_mask)))
    # Land pixel (999.0) must NOT influence mean or max!
    assert stats["maximum"] is not None
    assert stats["maximum"] < 10.0


def test_cloud_mask_excludes_scl_invalid_classes():
    """Verify SCL cloud and shadow classes are excluded."""
    # Classes: 3 = shadow, 8 = cloud med, 9 = cloud high, 6 = water
    scl = np.array([
        [6, 6, 6],
        [8, 9, 3],
        [0, 1, 6],
    ], dtype=np.uint8)

    clear_mask, cloud_pct, is_avail = SCLCloudMasker.create_mask(scl, (3, 3))
    assert is_avail is True
    # Row 0: all 6 (water) -> clear
    assert np.all(clear_mask[0, :])
    # Row 1: cloud/shadow (8, 9, 3) -> masked out
    assert not np.any(clear_mask[1, :])
    # Row 2: 0 (nodata), 1 (defective) -> masked out; 6 -> clear
    assert clear_mask[2, 2] == np.bool_(True)
    assert clear_mask[2, 0] == np.bool_(False)


def test_spectral_statistics_nodata_and_zero_division_safety():
    """Verify division by zero and invalid values produce safe statistical results."""
    data = np.array([[np.nan, np.inf], [-np.inf, 0.15]], dtype=np.float32)
    mask = np.ones((2, 2), dtype=bool)

    stats = SpectralStatistics.calculate(data, mask, total_water_pixels=4)
    # Only 1 valid pixel (0.15)
    assert stats["valid_pixel_count"] == 1
    # Minimum valid count threshold triggered -> INSUFFICIENT, no NaN/Inf crash
    assert stats["quality"] == "INSUFFICIENT"
    assert stats["value"] is None


def test_spectral_anomaly_baseline_calculation():
    """Verify historical mean, standard deviation, and z-score anomaly calculation."""
    # Historical observations of the same lake: [0.10, 0.12, 0.11, 0.09] -> mean ~0.105, std ~0.011
    hist = [0.10, 0.12, 0.11, 0.09]

    # Current value = 0.15 -> positive anomaly
    z, mean, std, quality, classification, desc = SpectralAnomalyIndicator.calculate_anomaly(0.15, hist)
    assert quality == "GOOD"
    assert z > 2.0  # More than 2 sigma above baseline
    assert classification == "HIGH ANOMALY"

    # Current value = 0.105 -> normal
    z_norm, _, _, _, class_norm, _ = SpectralAnomalyIndicator.calculate_anomaly(0.105, hist)
    assert abs(z_norm) < 1.0
    assert class_norm == "NORMAL"

    # Insufficient historical observations (< 3)
    z_few, _, _, quality_few, class_few, desc_few = SpectralAnomalyIndicator.calculate_anomaly(0.15, [0.10, 0.12])
    assert z_few is None
    assert quality_few == "LIMITED"
    assert class_few == "BASELINE UNAVAILABLE"
    assert "required historical observations" in desc_few


def test_spectral_api_endpoints_and_caching(client: TestClient, db_session: Session, tmp_path):
    """Test full spectral API: availability, analyze, caching, preview image, and summary."""
    # Create test water body
    wb = WaterBody(
        name="Spectral Verification Lake",
        normalized_name="spectral verification lake",
        country="India",
        min_lon=75.10,
        min_lat=19.10,
        max_lon=75.15,
        max_lat=19.15,
        area_sq_km=2.5,
    )
    db_session.add(wb)
    db_session.commit()

    # Create dummy observation directory and rgb.jpg
    obs_dir = tmp_path / "water_bodies" / wb.id / "observations" / "S2_SPECTRAL_TEST_01"
    spectral_dir = obs_dir / "spectral"
    spectral_dir.mkdir(parents=True, exist_ok=True)
    rgb_file = obs_dir / "rgb.jpg"

    from PIL import Image
    im = Image.new("RGB", (64, 64), color=(60, 130, 210))
    im.save(rgb_file, "JPEG")

    obs = SatelliteObservation(
        water_body_id=wb.id,
        satellite="Sentinel-2",
        provider="earth_search",
        collection="sentinel-2-c1-l2a",
        external_scene_id="S2_SPECTRAL_TEST_01",
        sensing_date=datetime(2024, 4, 15, tzinfo=timezone.utc),
        cloud_cover_percent=3.5,
        aoi_bounds=json.dumps([75.10, 19.10, 75.15, 19.15]),
        local_visual_path=str(rgb_file.relative_to(tmp_path)).replace("\\", "/"),
        status="ready",
    )
    db_session.add(obs)
    db_session.commit()

    with patch("app.services.spectral.service.settings.DATA_DIR", tmp_path), \
         patch("app.services.spectral.band_loader.settings.DATA_DIR", tmp_path):

        # 1. Check availability for NDTI (B04 & B03 available from visual asset)
        avail_res = client.get(f"/api/v1/water-bodies/{wb.id}/spectral/available?observation_id={obs.id}&indicator=ndti")
        assert avail_res.status_code == 200
        avail_data = avail_res.json()
        assert avail_data["is_ready"] is True
        assert "B04" in avail_data["available_bands"]
        assert "B03" in avail_data["available_bands"]

        # 2. Check availability for NDCI (B05 missing in pure RGB visual asset)
        avail_ndci = client.get(f"/api/v1/water-bodies/{wb.id}/spectral/available?observation_id={obs.id}&indicator=ndci")
        assert avail_ndci.status_code == 200
        ndci_data = avail_ndci.json()
        assert ndci_data["is_ready"] is False
        assert "B05" in ndci_data["missing_bands"]

        # 3. Analyze NDTI
        ana_res = client.post(
            f"/api/v1/water-bodies/{wb.id}/spectral/analyze",
            json={"observation_id": obs.id, "indicator": "ndti"},
        )
        assert ana_res.status_code == 200
        res_data = ana_res.json()
        assert res_data["indicator"] == "ndti"
        assert res_data["value"] is not None
        assert res_data["classification"] in ("LOW", "MODERATE", "HIGH")
        assert res_data["is_cached"] is False
        assert (spectral_dir / "ndti_result.json").exists()
        assert (spectral_dir / "ndti_preview.png").exists()

        # 4. Analyze NDTI again -> verify cache hit
        ana_res_cached = client.post(
            f"/api/v1/water-bodies/{wb.id}/spectral/analyze",
            json={"observation_id": obs.id, "indicator": "ndti"},
        )
        assert ana_res_cached.status_code == 200
        cached_data = ana_res_cached.json()
        assert cached_data["is_cached"] is True

        # 5. Fetch preview image
        prev_res = client.get(f"/api/v1/water-bodies/{wb.id}/spectral/results/{obs.id}_ndti/image")
        assert prev_res.status_code == 200
        assert prev_res.headers["content-type"] == "image/png"

        # 6. Multi-indicator summary endpoint
        sum_res = client.get(f"/api/v1/water-bodies/{wb.id}/spectral/summary?observation_id={obs.id}")
        assert sum_res.status_code == 200
        sum_data = sum_res.json()
        assert sum_data["indicators"]["ndti"] is not None
        assert sum_data["indicators"]["ndti"]["indicator"] == "ndti"
