from pathlib import Path
from typing import List


def get_repo_root() -> Path:
    """
    Returns the absolute path to the repository root directory.
    Assumes this file is located at <repo_root>/backend/app/core/paths.py.
    """
    return Path(__file__).resolve().parent.parent.parent.parent


def resolve_path(target_path: str | Path, base_dir: Path | None = None) -> Path:
    """
    Resolves a relative or absolute path against a base directory (defaults to repo root).
    """
    path = Path(target_path)
    if path.is_absolute():
        return path
    base = base_dir or get_repo_root()
    return (base / path).resolve()


def ensure_data_directories(data_dir: Path) -> List[Path]:
    """
    Ensures that standard JalNetra data storage directories exist.
    """
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
    created = []
    for sub in subdirs:
        target = data_dir / sub
        target.mkdir(parents=True, exist_ok=True)
        created.append(target)
    return created
