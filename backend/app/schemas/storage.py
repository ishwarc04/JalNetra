from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional


class StorageDirectoryStatus(BaseModel):
    path: str
    exists: bool
    is_directory: bool
    file_count: int


class StorageDatabaseCounts(BaseModel):
    water_bodies: int = 0
    satellite_scenes: int = 0
    satellite_assets: int = 0
    analysis_runs: int = 0
    cache_entries: int = 0
    size_bytes: int = 0
    size_formatted: str = "0 B"


class StorageFilesystemSizes(BaseModel):
    satellite_data_bytes: int = 0
    satellite_data_formatted: str = "0 B"
    processed_data_bytes: int = 0
    processed_data_formatted: str = "0 B"
    cache_bytes: int = 0
    cache_formatted: str = "0 B"
    total_bytes: int = 0
    total_formatted: str = "0 B"


class StorageOrphansSummary(BaseModel):
    orphan_scene_directories_count: int = 0
    orphan_scene_directories: List[str] = Field(default_factory=list)
    missing_scene_directories_count: int = 0
    missing_scene_directories: List[str] = Field(default_factory=list)


class StorageStatusResponse(BaseModel):
    database: Dict[str, Any]
    directories: Dict[str, str]
    details: Dict[str, StorageDirectoryStatus]
    database_counts: StorageDatabaseCounts = Field(default_factory=StorageDatabaseCounts)
    local_storage: StorageFilesystemSizes = Field(default_factory=StorageFilesystemSizes)
    orphans: StorageOrphansSummary = Field(default_factory=StorageOrphansSummary)


class DatabaseResetSummary(BaseModel):
    water_bodies_deleted: int = 0
    scenes_deleted: int = 0
    assets_deleted: int = 0
    analysis_runs_deleted: int = 0
    cache_entries_deleted: int = 0


class FilesystemResetSummary(BaseModel):
    files_deleted: int = 0
    bytes_freed: int = 0
    bytes_freed_formatted: str = "0 B"


class StorageResetResponse(BaseModel):
    success: bool
    operation: str
    message: str
    database: DatabaseResetSummary = Field(default_factory=DatabaseResetSummary)
    filesystem: FilesystemResetSummary = Field(default_factory=FilesystemResetSummary)
