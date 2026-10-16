#!/usr/bin/env python3
"""
JalNetra 2.0 - Storage and Database Reset CLI (Phase 1)
Allows safe, explicit reset of database records and local storage files.
Preserves schemas, migrations, configuration, and source code.
"""

import sys
import argparse
from pathlib import Path

# Add backend directory to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "backend"))

from app.db.database import SessionLocal
from app.services.storage.reset_service import reset_service, format_bytes


def main():
    parser = argparse.ArgumentParser(
        description="JalNetra 2.0 Safe Storage and Database Reset Tool"
    )
    parser.add_argument(
        "--status", action="store_true", help="Print current storage and database status"
    )
    parser.add_argument(
        "--clear-cache", action="store_true", help="Clear cache entries and files"
    )
    parser.add_argument(
        "--clear-processed", action="store_true", help="Clear processed imagery and runs"
    )
    parser.add_argument(
        "--clear-satellite", action="store_true", help="Clear satellite scenes and assets"
    )
    parser.add_argument(
        "--reset-all", action="store_true", help="Reset all project data (DB + files)"
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Confirm execution without interactive prompt"
    )

    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.status or (not any([args.clear_cache, args.clear_processed, args.clear_satellite, args.reset_all])):
            status = reset_service.collect_storage_status(db)
            print("=" * 60)
            print("JALNETRA 2.0 - STORAGE & DATABASE AUDIT")
            print("=" * 60)
            print("DATABASE COUNTS:")
            print(f"  Water Bodies:     {status.database_counts.water_bodies}")
            print(f"  Satellite Scenes: {status.database_counts.satellite_scenes}")
            print(f"  Satellite Assets: {status.database_counts.satellite_assets}")
            print(f"  Analysis Runs:    {status.database_counts.analysis_runs}")
            print(f"  Cache Entries:    {status.database_counts.cache_entries}")
            print(f"  Database Size:    {status.database_counts.size_formatted}")
            print("\nLOCAL STORAGE FOOTPRINT:")
            print(f"  Satellite Data:   {status.local_storage.satellite_data_formatted}")
            print(f"  Processed Data:   {status.local_storage.processed_data_formatted}")
            print(f"  Cache Storage:    {status.local_storage.cache_formatted}")
            print(f"  Total Data Size:  {status.local_storage.total_formatted}")
            print("\nORPHANS:")
            print(f"  Orphan Scenes:    {status.orphans.orphan_scene_directories_count}")
            print(f"  Missing Folders:  {status.orphans.missing_scene_directories_count}")
            print("=" * 60)
            if not any([args.clear_cache, args.clear_processed, args.clear_satellite, args.reset_all]):
                return

        def confirm(action: str) -> bool:
            if args.yes:
                return True
            ans = input(f"Are you sure you want to {action}? (y/N): ").strip().lower()
            return ans in ("y", "yes")

        if args.clear_cache:
            if confirm("CLEAR CACHE"):
                res = reset_service.clear_cache(db)
                print(f"[SUCCESS] {res.message}")

        if args.clear_processed:
            if confirm("CLEAR PROCESSED DATA"):
                res = reset_service.clear_processed_data(db)
                print(f"[SUCCESS] {res.message}")

        if args.clear_satellite:
            if confirm("CLEAR SATELLITE DATA"):
                res = reset_service.clear_satellite_data(db)
                print(f"[SUCCESS] {res.message}")

        if args.reset_all:
            if confirm("PERMANENTLY RESET ALL PROJECT DATA"):
                res = reset_service.reset_all_data(db)
                print(f"[SUCCESS] {res.message}")
                print(f"  Water bodies deleted: {res.database.water_bodies_deleted}")
                print(f"  Scenes deleted:       {res.database.scenes_deleted}")
                print(f"  Assets deleted:       {res.database.assets_deleted}")
                print(f"  Analysis deleted:     {res.database.analysis_runs_deleted}")
                print(f"  Cache deleted:        {res.database.cache_entries_deleted}")
                print(f"  Files deleted:        {res.filesystem.files_deleted}")
                print(f"  Bytes freed:          {res.filesystem.bytes_freed_formatted}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
