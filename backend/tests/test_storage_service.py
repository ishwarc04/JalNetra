import io
import pytest
from pathlib import Path
from app.services.storage_service import LocalStorageService, StoragePathTraversalError


def test_storage_directory_creation(tmp_path: Path):
    storage = LocalStorageService(base_dir=tmp_path)
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
        assert (tmp_path / sub).exists()
        assert (tmp_path / sub).is_dir()


def test_storage_save_and_read_bytes(tmp_path: Path):
    storage = LocalStorageService(base_dir=tmp_path)
    data = b"JalNetra 2.0 Test Payload"
    saved_path = storage.save_bytes("exports/test.txt", data)

    assert saved_path.exists()
    assert storage.exists("exports/test.txt")
    assert storage.read_bytes("exports/test.txt") == data
    assert storage.get_size("exports/test.txt") == len(data)


def test_storage_save_file_stream(tmp_path: Path):
    storage = LocalStorageService(base_dir=tmp_path)
    stream = io.BytesIO(b"Stream data for raster metadata")
    saved_path = storage.save_file("manifests/run.json", stream)

    assert saved_path.exists()
    assert storage.read_bytes("manifests/run.json") == b"Stream data for raster metadata"


def test_storage_sha256_calculation(tmp_path: Path):
    import hashlib

    storage = LocalStorageService(base_dir=tmp_path)
    content = b"Deterministic hash calculation content"
    storage.save_bytes("cache/test_item.bin", content)

    expected_hash = hashlib.sha256(content).hexdigest()
    calculated_hash = storage.calculate_sha256("cache/test_item.bin")
    assert calculated_hash == expected_hash


def test_storage_safe_path_traversal_prevention(tmp_path: Path):
    storage = LocalStorageService(base_dir=tmp_path)

    with pytest.raises(StoragePathTraversalError):
        storage.resolve_safe_path("../outside.txt")

    with pytest.raises(StoragePathTraversalError):
        storage.save_bytes("../../etc/passwd", b"evil")


def test_storage_delete(tmp_path: Path):
    storage = LocalStorageService(base_dir=tmp_path)
    storage.save_bytes("exports/temp.txt", b"delete me")
    assert storage.exists("exports/temp.txt")

    deleted = storage.delete("exports/temp.txt")
    assert deleted is True
    assert not storage.exists("exports/temp.txt")

    # Deleting non-existent returns False
    assert storage.delete("exports/temp.txt") is False


def test_storage_deterministic_helpers(tmp_path: Path):
    storage = LocalStorageService(base_dir=tmp_path)
    assert storage.get_scene_dir("scene-123") == (tmp_path / "scenes/scene-123").resolve()
    assert storage.get_processed_dir("run-456") == (tmp_path / "processed/run-456").resolve()
    assert storage.get_water_body_dir("wb-789") == (tmp_path / "water_bodies/wb-789").resolve()
    assert storage.get_cache_dir("cache-abc") == (tmp_path / "cache/cache-abc").resolve()
