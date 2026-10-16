import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO, Optional, Union
from app.core.config import settings
from app.core.paths import resolve_path


class StoragePathTraversalError(Exception):
    """Raised when a path escapes the allowed root data directory."""
    pass


class LocalStorageService:
    """
    Centralized local filesystem storage abstraction.
    Guarantees safe path containment, atomic writes, SHA256 hashing,
    and deterministic folder generation.
    """

    def __init__(self, base_dir: Optional[Union[str, Path]] = None):
        self.base_dir = (
            Path(base_dir).resolve() if base_dir else settings.resolved_data_dir
        )
        self.ensure_structure()

    def ensure_structure(self) -> None:
        """Ensures all standard JalNetra storage directories exist."""
        subdirs = [
            "database",
            "water_bodies",
            "scenes",
            "processed",
            "tiles",
            "cache",
            "exports",
            "manifests",
        ]
        for sub in subdirs:
            (self.base_dir / sub).mkdir(parents=True, exist_ok=True)

    def resolve_safe_path(self, relative_or_subpath: Union[str, Path]) -> Path:
        """
        Resolves a path relative to self.base_dir, preventing path traversal attacks.
        """
        target = (self.base_dir / relative_or_subpath).resolve()
        try:
            # Check if target is relative to base_dir
            target.relative_to(self.base_dir)
        except ValueError:
            raise StoragePathTraversalError(
                f"Path traversal detected: '{relative_or_subpath}' resolves outside storage base '{self.base_dir}'"
            )
        return target

    def get_path(self, relative_path: Union[str, Path]) -> Path:
        """Returns safe absolute Path."""
        return self.resolve_safe_path(relative_path)

    def exists(self, relative_path: Union[str, Path]) -> bool:
        """Checks if a file or directory exists."""
        target = self.resolve_safe_path(relative_path)
        return target.exists()

    def save_bytes(self, relative_path: Union[str, Path], data: bytes) -> Path:
        """
        Safely and atomically writes bytes to the given relative path.
        """
        target = self.resolve_safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write using a temporary file in the same directory
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, delete=False, mode="wb"
            ) as f:
                temp_file = Path(f.name)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

            # Atomic replace
            shutil.move(str(temp_file), str(target))
            temp_file = None
            return target
        finally:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

    def save_file(self, relative_path: Union[str, Path], file_obj: BinaryIO) -> Path:
        """
        Safely and atomically writes from a file-like stream.
        """
        target = self.resolve_safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, delete=False, mode="wb"
            ) as f:
                temp_file = Path(f.name)
                shutil.copyfileobj(file_obj, f)
                f.flush()
                os.fsync(f.fileno())

            shutil.move(str(temp_file), str(target))
            temp_file = None
            return target
        finally:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

    def read_bytes(self, relative_path: Union[str, Path]) -> bytes:
        """Reads bytes from file."""
        target = self.resolve_safe_path(relative_path)
        with open(target, "rb") as f:
            return f.read()

    def delete(self, relative_path: Union[str, Path]) -> bool:
        """Deletes a file if it exists. Returns True if deleted, False if not found."""
        target = self.resolve_safe_path(relative_path)
        if not target.exists():
            return False
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return True

    def get_size(self, relative_path: Union[str, Path]) -> int:
        """Returns file size in bytes."""
        target = self.resolve_safe_path(relative_path)
        return target.stat().st_size

    def calculate_sha256(self, relative_path: Union[str, Path]) -> str:
        """Calculates SHA256 hash of a file efficiently in chunks."""
        target = self.resolve_safe_path(relative_path)
        hasher = hashlib.sha256()
        with open(target, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    # Deterministic Path Generators
    def get_scene_dir(self, scene_id: str) -> Path:
        return self.resolve_safe_path(f"scenes/{scene_id}")

    def get_processed_dir(self, analysis_run_id: str) -> Path:
        return self.resolve_safe_path(f"processed/{analysis_run_id}")

    def get_water_body_dir(self, water_body_id: str) -> Path:
        return self.resolve_safe_path(f"water_bodies/{water_body_id}")

    def get_cache_dir(self, cache_key: str) -> Path:
        return self.resolve_safe_path(f"cache/{cache_key}")


storage_service = LocalStorageService()
