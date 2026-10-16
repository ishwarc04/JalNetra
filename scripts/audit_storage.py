#!/usr/bin/env python3
"""
JalNetra 2.0 - Storage and Database Audit Tool (Phase 0)
Performs a read-only inventory of database records, filesystem storage,
largest files, file extensions, and potential orphaned files.
Does NOT modify or delete any files or database records.
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


def get_repo_root() -> Path:
    """Finds repository root relative to this script."""
    return Path(__file__).resolve().parent.parent


def format_bytes(num_bytes: int) -> str:
    """Formats bytes into human readable format."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.2f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def collect_database_inventory(db_path: Path) -> Dict[str, Any]:
    """Inspects SQLite database in read-only mode."""
    inventory = {
        "connected": False,
        "path": str(db_path),
        "table_counts": {},
        "water_bodies": [],
        "satellite_scenes": [],
        "asset_keys": {},
        "cache_types": {},
    }

    if not db_path.exists():
        return inventory

    try:
        uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        cursor = conn.cursor()
        inventory["connected"] = True

        # List tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cursor.fetchall()]

        for table in tables:
            cursor.execute(f"SELECT count(*) FROM {table};")
            inventory["table_counts"][table] = cursor.fetchone()[0]

        # Detailed water bodies
        if "water_bodies" in tables:
            cursor.execute(
                "SELECT id, name, source, source_id, "
                "(geometry_geojson IS NOT NULL AND length(geometry_geojson) > 0) "
                "FROM water_bodies ORDER BY created_at ASC;"
            )
            for r in cursor.fetchall():
                inventory["water_bodies"].append({
                    "id": r[0],
                    "name": r[1],
                    "source": r[2],
                    "source_id": r[3],
                    "has_geometry": bool(r[4]),
                })

        # Detailed satellite scenes
        if "satellite_scenes" in tables:
            cursor.execute(
                "SELECT id, external_scene_id, sensing_start, cloud_cover_percent, status "
                "FROM satellite_scenes ORDER BY sensing_start DESC;"
            )
            for r in cursor.fetchall():
                inventory["satellite_scenes"].append({
                    "id": r[0],
                    "external_scene_id": r[1],
                    "sensing_start": str(r[2]) if r[2] else None,
                    "cloud_cover_percent": r[3],
                    "status": r[4],
                })

        # Asset keys
        if "satellite_assets" in tables:
            cursor.execute(
                "SELECT asset_key, count(*), sum(file_size_bytes) "
                "FROM satellite_assets GROUP BY asset_key;"
            )
            for r in cursor.fetchall():
                inventory["asset_keys"][r[0]] = {
                    "count": r[1],
                    "size_bytes": r[2] or 0,
                }

        # Cache types
        if "cache_entries" in tables:
            cursor.execute(
                "SELECT cache_type, source, count(*), sum(file_size_bytes) "
                "FROM cache_entries GROUP BY cache_type, source;"
            )
            for r in cursor.fetchall():
                key = f"{r[0]} ({r[1]})"
                inventory["cache_types"][key] = {
                    "count": r[2],
                    "size_bytes": r[3] or 0,
                }

        conn.close()
    except Exception as exc:
        inventory["error"] = str(exc)

    return inventory


def collect_filesystem_inventory(data_dir: Path, db_scenes: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Audits local data/ filesystem storage."""
    subdirs = [
        "scenes",
        "processed",
        "cache",
        "database",
        "water_bodies",
        "tiles",
        "exports",
        "manifests",
    ]

    inventory = {
        "data_dir": str(data_dir),
        "exists": data_dir.exists(),
        "subdirectories": {},
        "extension_counts": {},
        "largest_files": [],
        "total_files": 0,
        "total_size_bytes": 0,
        "orphans": {
            "scene_folders_not_in_db": [],
            "db_scenes_missing_folder": [],
        },
    }

    if not data_dir.exists():
        return inventory

    all_files = []

    for sub in subdirs:
        p = data_dir / sub
        if not p.exists():
            inventory["subdirectories"][sub] = {
                "exists": False,
                "file_count": 0,
                "size_bytes": 0,
            }
            continue

        files = [f for f in p.rglob("*") if f.is_file()]
        size = sum(f.stat().st_size for f in files)
        inventory["subdirectories"][sub] = {
            "exists": True,
            "file_count": len(files),
            "size_bytes": size,
        }
        all_files.extend(files)

    inventory["total_files"] = len(all_files)
    inventory["total_size_bytes"] = sum(f.stat().st_size for f in all_files)

    # Extension breakdown
    ext_map: Dict[str, int] = {}
    for f in all_files:
        ext = f.suffix.lower() if f.suffix else "[no_extension]"
        ext_map[ext] = ext_map.get(ext, 0) + 1
    inventory["extension_counts"] = dict(sorted(ext_map.items(), key=lambda x: -x[1]))

    # Largest files (top 10)
    sorted_files = sorted(all_files, key=lambda f: f.stat().st_size, reverse=True)[:10]
    for f in sorted_files:
        rel = f.relative_to(data_dir.parent).as_posix() if f.is_relative_to(data_dir.parent) else str(f)
        inventory["largest_files"].append({
            "path": rel,
            "size_bytes": f.stat().st_size,
        })

    # Orphan detection
    if db_scenes is not None:
        db_scene_ids = {s["id"] for s in db_scenes}
        scenes_dir = data_dir / "scenes"
        if scenes_dir.exists():
            for folder in scenes_dir.iterdir():
                if folder.is_dir() and folder.name not in db_scene_ids:
                    folder_files = list(folder.rglob("*"))
                    folder_size = sum(f.stat().st_size for f in folder_files if f.is_file())
                    inventory["orphans"]["scene_folders_not_in_db"].append({
                        "folder_name": folder.name,
                        "file_count": len([f for f in folder_files if f.is_file()]),
                        "size_bytes": folder_size,
                    })

        for s in db_scenes:
            sid = s["id"]
            if not (scenes_dir / sid).exists():
                inventory["orphans"]["db_scenes_missing_folder"].append({
                    "scene_id": sid,
                    "external_scene_id": s.get("external_scene_id", ""),
                })

    return inventory


def generate_audit_report(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Generates complete storage and database audit data structure."""
    root = repo_root or get_repo_root()
    data_dir = root / "data"
    db_path = data_dir / "database" / "jalnetra.db"

    db_data = collect_database_inventory(db_path)
    fs_data = collect_filesystem_inventory(data_dir, db_data.get("satellite_scenes", []))

    return {
        "repo_root": str(root),
        "database": db_data,
        "filesystem": fs_data,
    }


def print_audit_summary(report: Dict[str, Any]) -> None:
    """Prints a clean human-readable audit report to stdout."""
    db = report["database"]
    fs = report["filesystem"]

    print("==================================================")
    print("           JALNETRA 2.0 - STORAGE AUDIT           ")
    print("==================================================")
    print(f"Repository root : {report['repo_root']}")
    print(f"Database path   : {db['path']}")
    print(f"Data directory  : {fs['data_dir']}")
    print()

    print("Database Inventory")
    print("------------------")
    if not db["connected"]:
        print("Database not connected or does not exist.")
    else:
        tc = db["table_counts"]
        print(f"Water bodies:       {tc.get('water_bodies', 0):>6}")
        print(f"Satellite scenes:   {tc.get('satellite_scenes', 0):>6}")
        print(f"Satellite assets:   {tc.get('satellite_assets', 0):>6}")
        print(f"Analysis runs:      {tc.get('analysis_runs', 0):>6}")
        print(f"Cache entries:      {tc.get('cache_entries', 0):>6}")
    print()

    print("Filesystem Storage")
    print("------------------")
    subs = fs.get("subdirectories", {})
    order = ["scenes", "processed", "cache", "database", "water_bodies", "tiles", "exports", "manifests"]
    for s in order:
        info = subs.get(s, {"file_count": 0, "size_bytes": 0})
        name = s.capitalize() + ":"
        print(f"{name:16} {format_bytes(info['size_bytes']):>12}  ({info['file_count']} files)")

    print("--------------------------------------------------")
    print(f"{'Total:':16} {format_bytes(fs['total_size_bytes']):>12}  ({fs['total_files']} files)")
    print()

    print("File Extensions Breakdown")
    print("-------------------------")
    for ext, count in fs.get("extension_counts", {}).items():
        print(f"{ext:16}: {count:>6} files")
    print()

    print("Top 10 Largest Files")
    print("--------------------")
    for item in fs.get("largest_files", []):
        print(f"{format_bytes(item['size_bytes']):>12} | {item['path']}")
    print()

    orphans = fs.get("orphans", {})
    orphan_folders = orphans.get("scene_folders_not_in_db", [])
    missing_folders = orphans.get("db_scenes_missing_folder", [])

    print("Orphan Analysis")
    print("---------------")
    print(f"Scene folders on disk not in DB : {len(orphan_folders)}")
    for of in orphan_folders[:5]:
        print(f"  - {of['folder_name']} ({of['file_count']} files, {format_bytes(of['size_bytes'])})")
    if len(orphan_folders) > 5:
        print(f"  ... and {len(orphan_folders) - 5} more")

    print(f"DB scenes with missing disk folder : {len(missing_folders)}")
    for mf in missing_folders:
        print(f"  - {mf['scene_id']} ({mf['external_scene_id']})")
    print("==================================================")


if __name__ == "__main__":
    rep = generate_audit_report()
    print_audit_summary(rep)
