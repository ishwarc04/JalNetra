import json
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.db.models.water_body import WaterBody
from app.db.models.satellite_scene import SatelliteScene
from app.db.models.satellite_asset import SatelliteAsset
from app.services.discovery.models import (
    WaterBodyDiscoveryResult,
    BatchImportRequest,
)


def _make_sample_wb(
    source_id: str,
    name: str,
    lat: float = 18.52,
    lon: float = 73.85,
    area_sq_km: float = 0.5,
    provider: str = "osm",
) -> WaterBodyDiscoveryResult:
    """Helper to generate a valid WaterBodyDiscoveryResult with geojson polygon."""
    poly = {
        "type": "Polygon",
        "coordinates": [[
            [lon - 0.005, lat - 0.005],
            [lon + 0.005, lat - 0.005],
            [lon + 0.005, lat + 0.005],
            [lon - 0.005, lat + 0.005],
            [lon - 0.005, lat - 0.005],
        ]]
    }
    return WaterBodyDiscoveryResult(
        provider=provider,
        source_id=source_id,
        name=name,
        water_body_type="lake",
        country="India",
        centroid_lat=lat,
        centroid_lon=lon,
        min_lat=lat - 0.005,
        max_lat=lat + 0.005,
        min_lon=lon - 0.005,
        max_lon=lon + 0.005,
        area_sq_km=area_sq_km,
        geometry_geojson=json.dumps(poly),
    )


# 1. Single water body import via POST /api/v1/discovery/water-bodies/import
def test_single_water_body_import(client: TestClient, db_session: Session):
    wb = _make_sample_wb("way/single_lake_01", "Pashan Lake", 18.535, 73.785, 0.42)
    res = client.post("/api/v1/discovery/water-bodies/import", json=wb.model_dump())
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Pashan Lake"
    assert data["source_id"] == "way/single_lake_01"
    assert data["source"] == "osm"
    assert data["centroid_lat"] == 18.535
    assert data["centroid_lon"] == 73.785
    assert data["area_sq_km"] == 0.42
    assert data["geometry_geojson"] is not None

    # Verify directly in DB
    db_row = db_session.execute(
        select(WaterBody).where(WaterBody.source_id == "way/single_lake_01")
    ).scalar_one_or_none()
    assert db_row is not None
    assert db_row.name == "Pashan Lake"
    assert db_row.geometry_hash is not None


# 2. Batch import multiple water bodies via POST /api/v1/discovery/water-bodies/import-batch
def test_batch_import_multiple_water_bodies(client: TestClient, db_session: Session):
    wb1 = _make_sample_wb("way/batch_lake_01", "Katraj Lake", 18.455, 73.865, 0.35)
    wb2 = _make_sample_wb("way/batch_lake_02", "Pashan Lake North", 18.540, 73.790, 0.22)
    wb3 = _make_sample_wb("way/batch_lake_03", "Mastani Lake", 18.390, 73.980, 0.15)

    batch_payload = {"water_bodies": [wb1.model_dump(), wb2.model_dump(), wb3.model_dump()]}
    res = client.post("/api/v1/discovery/water-bodies/import-batch", json=batch_payload)
    assert res.status_code == 200
    data = res.json()

    assert data["total_requested"] == 3
    assert data["imported_count"] == 3
    assert data["already_existed_count"] == 0
    assert data["failed_count"] == 0
    assert len(data["results"]) == 3

    for item in data["results"]:
        assert item["status"] == "imported"
        assert item["water_body"] is not None
        assert item["water_body"]["id"] is not None

    # Verify all 3 in DB
    source_ids = ["way/batch_lake_01", "way/batch_lake_02", "way/batch_lake_03"]
    db_count = db_session.execute(
        select(func.count(WaterBody.id)).where(WaterBody.source_id.in_(source_ids))
    ).scalar()
    assert db_count == 3


# 3. Batch import deduplication and idempotence (mixed new and existing)
def test_batch_import_deduplication_and_idempotence(client: TestClient, db_session: Session):
    # Pre-register wb1
    wb1 = _make_sample_wb("way/idem_lake_01", "Pre-existing Lake", 18.50, 73.80, 0.5)
    res_pre = client.post("/api/v1/discovery/water-bodies/import", json=wb1.model_dump())
    assert res_pre.status_code == 201
    pre_id = res_pre.json()["id"]

    # Now attempt batch with wb1 (already exists) + wb2 (new) + duplicate wb1 in same payload
    wb2 = _make_sample_wb("way/idem_lake_02", "New Batch Lake", 18.60, 73.70, 0.3)
    batch_payload = {"water_bodies": [wb1.model_dump(), wb2.model_dump(), wb1.model_dump()]}

    res = client.post("/api/v1/discovery/water-bodies/import-batch", json=batch_payload)
    assert res.status_code == 200
    data = res.json()

    assert data["total_requested"] == 3
    assert data["imported_count"] == 1  # Only wb2 is new
    assert data["already_existed_count"] == 2  # wb1 pre-existing and duplicated
    assert data["failed_count"] == 0

    # First result is already_registered with pre_id
    assert data["results"][0]["status"] == "already_registered"
    assert data["results"][0]["source_id"] == "way/idem_lake_01"
    assert data["results"][0]["water_body"]["id"] == pre_id

    # Second result is newly imported
    assert data["results"][1]["status"] == "imported"
    assert data["results"][1]["source_id"] == "way/idem_lake_02"

    # Third result is also already_registered with pre_id
    assert data["results"][2]["status"] == "already_registered"
    assert data["results"][2]["water_body"]["id"] == pre_id

    # Verify no duplicate entries in database
    db_count_1 = db_session.execute(
        select(func.count(WaterBody.id)).where(WaterBody.source_id == "way/idem_lake_01")
    ).scalar()
    assert db_count_1 == 1


# 4. Geometry derivation and enrichment when centroid/bounds are omitted
def test_batch_import_geometry_enrichment(client: TestClient, db_session: Session):
    # Payload with geometry_geojson only, no centroid_lat/lon or min/max bounds
    poly = {
        "type": "Polygon",
        "coordinates": [[
            [77.10, 28.50],
            [77.20, 28.50],
            [77.20, 28.60],
            [77.10, 28.60],
            [77.10, 28.50],
        ]]
    }
    wb = WaterBodyDiscoveryResult(
        provider="osm",
        source_id="relation/enrich_test_01",
        name="Auto Enriched Lake",
        water_body_type="reservoir",
        geometry_geojson=json.dumps(poly),
        # centroid and bounds omitted (None)
    )

    batch_payload = {"water_bodies": [wb.model_dump()]}
    res = client.post("/api/v1/discovery/water-bodies/import-batch", json=batch_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["imported_count"] == 1
    imported_wb = data["results"][0]["water_body"]

    # Verify centroid and bbox were enriched automatically
    assert imported_wb["centroid_lat"] == pytest.approx(28.55, abs=0.01)
    assert imported_wb["centroid_lon"] == pytest.approx(77.15, abs=0.01)
    assert imported_wb["area_sq_km"] > 0


# 5. Validation error on malformed/invalid batch request
def test_batch_import_validation_error(client: TestClient):
    # Empty water_bodies list
    res_empty = client.post("/api/v1/discovery/water-bodies/import-batch", json={"water_bodies": []})
    assert res_empty.status_code == 422

    # Missing water_bodies key
    res_missing = client.post("/api/v1/discovery/water-bodies/import-batch", json={})
    assert res_missing.status_code == 422

    # Non-list water_bodies
    res_invalid = client.post("/api/v1/discovery/water-bodies/import-batch", json={"water_bodies": "invalid"})
    assert res_invalid.status_code == 422


# 6. Safety invariant: importing water bodies NEVER creates satellite scenes or assets
def test_import_safety_invariant_zero_satellite_data(client: TestClient, db_session: Session):
    # Count scenes and assets before import
    scenes_before = db_session.execute(select(func.count(SatelliteScene.id))).scalar()
    assets_before = db_session.execute(select(func.count(SatelliteAsset.id))).scalar()

    # Import single
    wb_single = _make_sample_wb("way/safety_single_01", "Safety Test Single Lake", 19.0, 74.0)
    res1 = client.post("/api/v1/discovery/water-bodies/import", json=wb_single.model_dump())
    assert res1.status_code == 201

    # Import batch
    wb_batch = [
        _make_sample_wb("way/safety_batch_01", "Safety Batch Lake 1", 19.1, 74.1),
        _make_sample_wb("way/safety_batch_02", "Safety Batch Lake 2", 19.2, 74.2),
    ]
    res2 = client.post(
        "/api/v1/discovery/water-bodies/import-batch",
        json={"water_bodies": [wb.model_dump() for wb in wb_batch]}
    )
    assert res2.status_code == 200

    # Count scenes and assets after import
    scenes_after = db_session.execute(select(func.count(SatelliteScene.id))).scalar()
    assets_after = db_session.execute(select(func.count(SatelliteAsset.id))).scalar()

    # Invariant: No scenes or assets must be created during import
    assert scenes_after == scenes_before
    assert assets_after == assets_before
