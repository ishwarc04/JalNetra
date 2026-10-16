"""
Tests for scripts/audit_storage.py (Phase 0).
Verifies:
- Discovery of storage paths
- Calculation of directory and file sizes
- Handling of empty and missing directories
- Database row collection in read-only mode
- Orphan folder detection
- Script does not modify or delete data
"""

import sys
import sqlite3
from pathlib import Path
import pytest

# Ensure scripts module is importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_storage import (
    format_bytes,
    collect_database_inventory,
    collect_filesystem_inventory,
    generate_audit_report,
)


def test_format_bytes():
    assert format_bytes(500) == "500 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1024 * 1024 * 5) == "5.00 MB"
    assert format_bytes(1024 * 1024 * 1024 * 2) == "2.00 GB"


def test_audit_filesystem_empty_and_missing_directories(tmp_path: Path):
    """Verifies that non-existent or empty directories are handled gracefully."""
    data_dir = tmp_path / "data"
    # data_dir does not exist yet
    res_missing = collect_filesystem_inventory(data_dir)
    assert res_missing["exists"] is False
    assert res_missing["total_files"] == 0
    assert res_missing["total_size_bytes"] == 0

    # Create empty data_dir with some empty subdirectories
    data_dir.mkdir(parents=True)
    (data_dir / "scenes").mkdir()
    (data_dir / "database").mkdir()

    res_empty = collect_filesystem_inventory(data_dir)
    assert res_empty["exists"] is True
    assert res_empty["total_files"] == 0
    assert res_empty["total_size_bytes"] == 0
    assert res_empty["subdirectories"]["scenes"]["file_count"] == 0
    assert res_empty["subdirectories"]["cache"]["exists"] is False


def test_audit_filesystem_sizes_and_orphans(tmp_path: Path):
    """Verifies calculation of sizes, extension counts, largest files, and orphans."""
    data_dir = tmp_path / "data"
    scenes_dir = data_dir / "scenes"
    scene_a = scenes_dir / "scene-uuid-1" / "assets"
    scene_b = scenes_dir / "scene-orphan-2" / "assets"
    scene_a.mkdir(parents=True)
    scene_b.mkdir(parents=True)

    # Create some dummy files
    f1 = scene_a / "B04.tif"
    f1.write_bytes(b"x" * 1000)

    f2 = scene_a / "metadata.json"
    f2.write_bytes(b"x" * 200)

    f3 = scene_b / "orphan.tif"
    f3.write_bytes(b"x" * 500)

    db_scenes = [{"id": "scene-uuid-1", "external_scene_id": "S2A_1"}, {"id": "scene-missing-on-disk", "external_scene_id": "S2A_2"}]

    res = collect_filesystem_inventory(data_dir, db_scenes=db_scenes)
    assert res["total_files"] == 3
    assert res["total_size_bytes"] == 1700
    assert res["subdirectories"]["scenes"]["file_count"] == 3
    assert res["subdirectories"]["scenes"]["size_bytes"] == 1700
    assert res["extension_counts"][".tif"] == 2
    assert res["extension_counts"][".json"] == 1
    assert len(res["largest_files"]) == 3
    assert res["largest_files"][0]["size_bytes"] == 1000

    # Orphan checks
    orphan_folders = res["orphans"]["scene_folders_not_in_db"]
    assert len(orphan_folders) == 1
    assert orphan_folders[0]["folder_name"] == "scene-orphan-2"

    missing_folders = res["orphans"]["db_scenes_missing_folder"]
    assert len(missing_folders) == 1
    assert missing_folders[0]["scene_id"] == "scene-missing-on-disk"


def test_audit_database_inventory(tmp_path: Path):
    """Verifies SQLite read-only collection with custom sqlite db fixture."""
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("CREATE TABLE water_bodies (id TEXT PRIMARY KEY, name TEXT, source TEXT, source_id TEXT, geometry_geojson TEXT, created_at TEXT);")
    cur.execute("CREATE TABLE satellite_scenes (id TEXT PRIMARY KEY, external_scene_id TEXT, sensing_start TEXT, cloud_cover_percent REAL, status TEXT);")
    cur.execute("INSERT INTO water_bodies VALUES ('wb-1', 'Test Lake', 'osm', 'way/1', '{\"type\":\"Point\"}', '2026-01-01');")
    cur.execute("INSERT INTO satellite_scenes VALUES ('sc-1', 'S2A_TEST', '2026-01-01T00:00:00', 5.0, 'downloaded');")
    conn.commit()
    conn.close()

    res = collect_database_inventory(db_file)
    assert res["connected"] is True
    assert res["table_counts"]["water_bodies"] == 1
    assert res["table_counts"]["satellite_scenes"] == 1
    assert len(res["water_bodies"]) == 1
    assert res["water_bodies"][0]["name"] == "Test Lake"
    assert res["water_bodies"][0]["has_geometry"] is True
    assert len(res["satellite_scenes"]) == 1
    assert res["satellite_scenes"][0]["external_scene_id"] == "S2A_TEST"


def test_audit_is_read_only(tmp_path: Path):
    """Verifies that running audit produces zero modifications on filesystem and database."""
    db_file = tmp_path / "test_ro.db"
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("CREATE TABLE water_bodies (id TEXT PRIMARY KEY, name TEXT, source TEXT, source_id TEXT, geometry_geojson TEXT, created_at TEXT);")
    cur.execute("INSERT INTO water_bodies VALUES ('wb-1', 'Test Lake', 'osm', 'way/1', NULL, '2026-01-01');")
    conn.commit()
    conn.close()

    db_mtime_before = db_file.stat().st_mtime_ns
    db_size_before = db_file.stat().st_size

    # Run audit
    res = collect_database_inventory(db_file)
    assert res["connected"] is True

    db_mtime_after = db_file.stat().st_mtime_ns
    db_size_after = db_file.stat().st_size

    assert db_size_before == db_size_after
    assert db_mtime_before == db_mtime_after


def test_generate_audit_report_on_actual_project():
    """Verifies generate_audit_report works on current workspace without crashing."""
    report = generate_audit_report(REPO_ROOT)
    assert "repo_root" in report
    assert "database" in report
    assert "filesystem" in report
    assert report["database"]["connected"] is True
    assert report["database"]["table_counts"]["water_bodies"] >= 0
