import os
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, delete, func, text

from app.core.config import settings
from app.db.models.water_body import WaterBody
from app.db.models.satellite_scene import SatelliteScene
from app.db.models.satellite_asset import SatelliteAsset
from app.db.models.analysis_run import AnalysisRun
from app.db.models.cache_entry import CacheEntry
from app.services.storage_service import (
    LocalStorageService,
    StoragePathTraversalError,
    storage_service,
)
from app.schemas.storage import (
    StorageStatusResponse,
    StorageDirectoryStatus,
    StorageDatabaseCounts,
    StorageFilesystemSizes,
    StorageOrphansSummary,
    DatabaseResetSummary,
    FilesystemResetSummary,
    StorageResetResponse,
)

logger = logging.getLogger("jalnetra.storage_reset")


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


class StorageResetService:
    """
    Dedicated service for safe database truncation, cache clearance,
    satellite imagery cleanup, and full project reset.
    Guarantees strict containment inside data/ directory.
    """

    def __init__(self, storage: Optional[LocalStorageService] = None):
        self.storage = storage or storage_service

    def _safe_clear_directory(self, relative_dir_name: str) -> Tuple[int, int]:
        """
        Safely clears all contents inside a subdirectory under data/.
        Preserves .gitkeep files.
        Never deletes the subdirectory itself or anything outside.
        Returns (files_deleted, bytes_freed).
        """
        # Validate that the relative dir does not try to traverse or point to forbidden targets
        if relative_dir_name in ("", ".", "/", "\\", "database"):
            raise ValueError(f"Direct deletion of protected target '{relative_dir_name}' is forbidden.")

        target_dir = self.storage.resolve_safe_path(relative_dir_name)
        if not target_dir.exists() or not target_dir.is_dir():
            return 0, 0

        # Strict containment verification
        try:
            target_dir.relative_to(self.storage.base_dir)
        except ValueError:
            raise StoragePathTraversalError(
                f"Path {target_dir} is outside storage root {self.storage.base_dir}"
            )

        files_deleted = 0
        bytes_freed = 0

        # Traverse directory contents
        for root, dirs, files in os.walk(target_dir, topdown=False):
            root_path = Path(root)
            for file_name in files:
                if file_name == ".gitkeep":
                    continue
                file_path = root_path / file_name
                try:
                    if file_path.is_file() or file_path.is_symlink():
                        size = file_path.stat().st_size
                        file_path.unlink()
                        files_deleted += 1
                        bytes_freed += size
                except OSError as err:
                    logger.warning("Failed to delete file %s: %s", file_path, err)

            for dir_name in dirs:
                dir_path = root_path / dir_name
                try:
                    # Only remove if directory is completely empty or only had deleted items
                    if dir_path.exists() and not any(dir_path.iterdir()):
                        dir_path.rmdir()
                except OSError as err:
                    logger.warning("Failed to remove empty folder %s: %s", dir_path, err)

        # Ensure .gitkeep is in place so git tracking is retained
        gitkeep = target_dir / ".gitkeep"
        if not gitkeep.exists():
            try:
                gitkeep.touch()
            except OSError:
                pass

        return files_deleted, bytes_freed

    def get_directory_size_and_files(self, relative_or_path: Path) -> Tuple[int, int]:
        """Calculates total size (bytes) and file count in a directory, ignoring .gitkeep."""
        if not relative_or_path.exists() or not relative_or_path.is_dir():
            return 0, 0
        total_size = 0
        total_files = 0
        for root, _, files in os.walk(relative_or_path):
            for f in files:
                if f == ".gitkeep":
                    continue
                fp = Path(root) / f
                try:
                    total_size += fp.stat().st_size
                    total_files += 1
                except OSError:
                    pass
        return total_size, total_files

    def collect_storage_status(self, db: Session) -> StorageStatusResponse:
        """
        Inspects database counts and local filesystem storage footprint.
        Identifies orphan scenes and missing scene directories.
        """
        base_dir = self.storage.base_dir

        # 1. Database table counts
        wb_count = db.execute(select(func.count()).select_from(WaterBody)).scalar() or 0
        scene_count = db.execute(select(func.count()).select_from(SatelliteScene)).scalar() or 0
        asset_count = db.execute(select(func.count()).select_from(SatelliteAsset)).scalar() or 0
        run_count = db.execute(select(func.count()).select_from(AnalysisRun)).scalar() or 0
        cache_count = db.execute(select(func.count()).select_from(CacheEntry)).scalar() or 0

        # Database file size
        db_file = base_dir / "database" / "jalnetra.db"
        db_size_bytes = db_file.stat().st_size if db_file.exists() else 0

        # 2. Filesystem folder sizes
        scenes_dir = base_dir / "scenes"
        processed_dir = base_dir / "processed"
        cache_dir = base_dir / "cache"

        scenes_bytes, _ = self.get_directory_size_and_files(scenes_dir)
        processed_bytes, _ = self.get_directory_size_and_files(processed_dir)
        cache_bytes, _ = self.get_directory_size_and_files(cache_dir)
        total_data_bytes, _ = self.get_directory_size_and_files(base_dir)
        # Add db size to total if in database/
        if db_size_bytes > 0:
            total_data_bytes += db_size_bytes

        # 3. Detect orphans
        # DB scenes
        db_scenes = db.execute(select(SatelliteScene.id, SatelliteScene.external_scene_id)).all()
        db_scene_keys = set()
        for s_id, ext_id in db_scenes:
            if s_id:
                db_scene_keys.add(s_id)
            if ext_id:
                db_scene_keys.add(ext_id)

        disk_scene_folders: List[str] = []
        if scenes_dir.exists():
            disk_scene_folders = [
                d.name for d in scenes_dir.iterdir()
                if d.is_dir() and d.name != ".gitkeep"
            ]

        orphan_scene_folders = [f for f in disk_scene_folders if f not in db_scene_keys]
        missing_scene_folders = [
            ext_id for s_id, ext_id in db_scenes
            if (scenes_dir / ext_id).exists() is False and (scenes_dir / s_id).exists() is False
        ]

        # 4. Detailed directory summary
        subdirs = [
            "data",
            "database",
            "water_bodies",
            "scenes",
            "processed",
            "tiles",
            "cache",
            "exports",
            "manifests",
        ]
        directories_summary: Dict[str, str] = {}
        details: Dict[str, StorageDirectoryStatus] = {}

        for sub in subdirs:
            dir_path = base_dir if sub == "data" else base_dir / sub
            exists = dir_path.exists()
            is_dir = dir_path.is_dir() if exists else False
            file_count = len([f for f in dir_path.iterdir() if f.name != ".gitkeep"]) if is_dir else 0

            directories_summary[sub] = "ok" if (exists and is_dir) else "missing"
            rel_str = f"./data/{sub}" if sub != "data" else "./data"
            details[sub] = StorageDirectoryStatus(
                path=rel_str,
                exists=exists,
                is_directory=is_dir,
                file_count=file_count,
            )

        db_status = "ok"
        try:
            db.execute(text("SELECT 1"))
        except Exception as e:
            db_status = f"error: {str(e)}"

        return StorageStatusResponse(
            database={
                "status": db_status,
                "engine": "sqlite",
                "url_type": "sqlite_local",
                "size_bytes": db_size_bytes,
                "size_formatted": format_bytes(db_size_bytes),
                "water_bodies": wb_count,
                "scenes": scene_count,
                "assets": asset_count,
                "analysis_runs": run_count,
                "cache_entries": cache_count,
            },
            directories=directories_summary,
            details=details,
            database_counts=StorageDatabaseCounts(
                water_bodies=wb_count,
                satellite_scenes=scene_count,
                satellite_assets=asset_count,
                analysis_runs=run_count,
                cache_entries=cache_count,
                size_bytes=db_size_bytes,
                size_formatted=format_bytes(db_size_bytes),
            ),
            local_storage=StorageFilesystemSizes(
                satellite_data_bytes=scenes_bytes,
                satellite_data_formatted=format_bytes(scenes_bytes),
                processed_data_bytes=processed_bytes,
                processed_data_formatted=format_bytes(processed_bytes),
                cache_bytes=cache_bytes,
                cache_formatted=format_bytes(cache_bytes),
                total_bytes=total_data_bytes,
                total_formatted=format_bytes(total_data_bytes),
            ),
            orphans=StorageOrphansSummary(
                orphan_scene_directories_count=len(orphan_scene_folders),
                orphan_scene_directories=orphan_scene_folders[:50],
                missing_scene_directories_count=len(missing_scene_folders),
                missing_scene_directories=missing_scene_folders[:50],
            ),
        )

    def reset_database(self, db: Session) -> DatabaseResetSummary:
        """
        Safely deletes all application records in dependency order.
        Preserves Alembic version table and database schema.
        """
        # Count prior to delete
        runs_del = db.execute(select(func.count()).select_from(AnalysisRun)).scalar() or 0
        assets_del = db.execute(select(func.count()).select_from(SatelliteAsset)).scalar() or 0
        scenes_del = db.execute(select(func.count()).select_from(SatelliteScene)).scalar() or 0
        cache_del = db.execute(select(func.count()).select_from(CacheEntry)).scalar() or 0
        wb_del = db.execute(select(func.count()).select_from(WaterBody)).scalar() or 0

        # Execute deletes in child-to-parent order
        db.execute(delete(AnalysisRun))
        db.execute(delete(SatelliteAsset))
        db.execute(delete(SatelliteScene))
        db.execute(delete(CacheEntry))
        db.execute(delete(WaterBody))
        db.commit()

        logger.info(
            "Database reset executed: %d runs, %d assets, %d scenes, %d cache, %d water bodies deleted.",
            runs_del, assets_del, scenes_del, cache_del, wb_del
        )

        return DatabaseResetSummary(
            water_bodies_deleted=wb_del,
            scenes_deleted=scenes_del,
            assets_deleted=assets_del,
            analysis_runs_deleted=runs_del,
            cache_entries_deleted=cache_del,
        )

    def clear_cache(self, db: Session) -> StorageResetResponse:
        """
        Clears all cache entries from database and data/cache/ filesystem directory.
        """
        cache_del = db.execute(select(func.count()).select_from(CacheEntry)).scalar() or 0
        db.execute(delete(CacheEntry))
        db.commit()

        files_del, bytes_freed = self._safe_clear_directory("cache")

        return StorageResetResponse(
            success=True,
            operation="clear_cache",
            message=f"Cache cleared successfully. Deleted {cache_del} database entries and freed {format_bytes(bytes_freed)}.",
            database=DatabaseResetSummary(cache_entries_deleted=cache_del),
            filesystem=FilesystemResetSummary(
                files_deleted=files_del,
                bytes_freed=bytes_freed,
                bytes_freed_formatted=format_bytes(bytes_freed),
            ),
        )

    def clear_processed_data(self, db: Session) -> StorageResetResponse:
        """
        Clears all analysis runs from database and data/processed/ directory.
        """
        runs_del = db.execute(select(func.count()).select_from(AnalysisRun)).scalar() or 0
        db.execute(delete(AnalysisRun))
        db.commit()

        files_del, bytes_freed = self._safe_clear_directory("processed")

        return StorageResetResponse(
            success=True,
            operation="clear_processed",
            message=f"Processed data cleared successfully. Deleted {runs_del} analysis runs and freed {format_bytes(bytes_freed)}.",
            database=DatabaseResetSummary(analysis_runs_deleted=runs_del),
            filesystem=FilesystemResetSummary(
                files_deleted=files_del,
                bytes_freed=bytes_freed,
                bytes_freed_formatted=format_bytes(bytes_freed),
            ),
        )

    def clear_satellite_data(self, db: Session) -> StorageResetResponse:
        """
        Clears all satellite scenes, assets, and raw GeoTIFF scene folders.
        Also removes analysis runs that depended on those scenes.
        """
        runs_del = db.execute(select(func.count()).select_from(AnalysisRun)).scalar() or 0
        assets_del = db.execute(select(func.count()).select_from(SatelliteAsset)).scalar() or 0
        scenes_del = db.execute(select(func.count()).select_from(SatelliteScene)).scalar() or 0

        db.execute(delete(AnalysisRun))
        db.execute(delete(SatelliteAsset))
        db.execute(delete(SatelliteScene))
        db.commit()

        files_del, bytes_freed = self._safe_clear_directory("scenes")

        return StorageResetResponse(
            success=True,
            operation="clear_satellite",
            message=f"Satellite data cleared successfully. Deleted {scenes_del} scenes, {assets_del} assets, and freed {format_bytes(bytes_freed)}.",
            database=DatabaseResetSummary(
                scenes_deleted=scenes_del,
                assets_deleted=assets_del,
                analysis_runs_deleted=runs_del,
            ),
            filesystem=FilesystemResetSummary(
                files_deleted=files_del,
                bytes_freed=bytes_freed,
                bytes_freed_formatted=format_bytes(bytes_freed),
            ),
        )

    def reset_all_data(self, db: Session) -> StorageResetResponse:
        """
        Full project reset:
        Truncates all database application tables (water bodies, scenes, assets, analysis, cache).
        Removes all scenes, processed imagery, cache, water body exports, tiles, manifests.
        Preserves schema, alembic_version, and folder .gitkeep files.
        """
        db_summary = self.reset_database(db)

        total_files = 0
        total_bytes = 0

        target_subdirs = [
            "scenes",
            "processed",
            "cache",
            "water_bodies",
            "tiles",
            "exports",
            "manifests",
        ]

        for subdir in target_subdirs:
            f_del, b_freed = self._safe_clear_directory(subdir)
            total_files += f_del
            total_bytes += b_freed

        # Re-ensure directory structure
        self.storage.ensure_structure()

        return StorageResetResponse(
            success=True,
            operation="reset_all_data",
            message=f"Complete project reset successful. Cleared database records and freed {format_bytes(total_bytes)} across {total_files} files.",
            database=db_summary,
            filesystem=FilesystemResetSummary(
                files_deleted=total_files,
                bytes_freed=total_bytes,
                bytes_freed_formatted=format_bytes(total_bytes),
            ),
        )


reset_service = StorageResetService()
