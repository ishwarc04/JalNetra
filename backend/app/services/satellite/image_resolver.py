import json
import logging
from pathlib import Path
from typing import Optional, Set, Tuple, List, Any
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import settings
from app.core.paths import get_repo_root
from app.db.models.satellite_observation import SatelliteObservation

logger = logging.getLogger("jalnetra.satellite.image_resolver")

SUPPORTED_IMAGE_EXTENSIONS: Set[str] = {".jpg", ".jpeg", ".png", ".webp"}


class ObservationImageResolver:
    """
    Authoritative visual image resolver for satellite observations.
    Safely resolves, verifies, and validates local visual image assets across
    multiple database fields, observation directory conventions, and path formats.
    """

    @classmethod
    def _is_valid_image_file(cls, path: Path) -> bool:
        """Verifies existence, regular file, supported extension, and non-zero size."""
        try:
            if not path.exists() or not path.is_file():
                return False
            if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
                return False
            if path.stat().st_size <= 0:
                return False
            return True
        except (OSError, PermissionError):
            return False

    @classmethod
    def _is_safe_path(cls, path: Path, base_dir: Path) -> bool:
        """Prevents directory traversal escaping base_dir."""
        try:
            if ".." in path.parts:
                return False
            resolved = str(path.resolve()).lower()
            base_resolved = str(base_dir.resolve()).lower()
            return resolved.startswith(base_resolved)
        except Exception:
            return False

    @classmethod
    def resolve_visual_image(
        cls,
        observation: SatelliteObservation,
        data_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        """
        Resolves the actual local filesystem image file for a SatelliteObservation.
        Handles:
          - data/...
          - ./data/...
          - absolute filesystem paths
          - water-body-relative paths (e.g. water_bodies/{wb_id}/observations/{scene}/rgb.jpg)
          - observation-relative paths
          - local_rgb_path, local_cropped_path, local_visual_path, local_path
          - metadata.json fallback
          - observation directory scan for supported images (.jpg, .jpeg, .png, .webp)
        Returns a validated Path if valid, else None.
        """
        if observation is None:
            return None

        wb_id = str(observation.water_body_id)
        scene_id = getattr(observation, "external_scene_id", None) or getattr(observation, "scene_id", None) or ""

        # Build ordered list of base directories to search
        repo_root = get_repo_root()
        candidate_base_dirs: List[Path] = []
        if data_dir:
            candidate_base_dirs.append(data_dir.resolve())
        candidate_base_dirs.append(settings.resolved_data_dir.resolve())
        candidate_base_dirs.append((repo_root / "data").resolve())
        candidate_base_dirs.append((repo_root / "backend" / "data").resolve())

        # Deduplicate while preserving order
        unique_base_dirs: List[Path] = []
        seen_dirs = set()
        for b in candidate_base_dirs:
            key = str(b).lower()
            if key not in seen_dirs:
                seen_dirs.add(key)
                unique_base_dirs.append(b)

        # Collect raw candidate path strings from all observation attributes
        raw_candidates: List[str] = []
        for attr in ("local_visual_path", "local_rgb_path", "local_cropped_path", "local_path"):
            val = getattr(observation, attr, None)
            if val and isinstance(val, str) and val.strip():
                raw_candidates.append(val.strip())

        # Collect from metadata_json if present
        metadata_raw = getattr(observation, "metadata_json", None)
        if metadata_raw:
            try:
                meta = json.loads(metadata_raw) if isinstance(metadata_raw, str) else metadata_raw
                if isinstance(meta, dict):
                    for key in ("local_visual_path", "local_rgb_path", "local_cropped_path", "image_path", "visual_path", "rgb_path", "path"):
                        val = meta.get(key)
                        if val and isinstance(val, str) and val.strip():
                            raw_candidates.append(val.strip())
            except Exception as e:
                logger.debug("Error parsing metadata_json for observation %s: %s", observation.id, e)

        # 1. Test candidate paths directly and against each base directory
        for raw_path_str in raw_candidates:
            p = Path(raw_path_str)
            if p.is_absolute():
                if cls._is_valid_image_file(p):
                    return p
            else:
                for base_dir in unique_base_dirs:
                    parts = p.parts
                    if len(parts) > 0 and parts[0] in ("data", ".data"):
                        cand = base_dir / Path(*parts[1:])
                    elif len(parts) > 1 and parts[0] == "." and parts[1] == "data":
                        cand = base_dir / Path(*parts[2:])
                    elif parts and parts[0] == "water_bodies":
                        cand = base_dir / p
                    elif parts and parts[0] == "observations":
                        cand = base_dir / "water_bodies" / wb_id / p
                    else:
                        cand = base_dir / p

                    if cls._is_safe_path(cand, base_dir) and cls._is_valid_image_file(cand):
                        return cand

                    # Also test resolving against repo_root if raw path started with "data/"
                    cand_repo = repo_root / p
                    if cls._is_valid_image_file(cand_repo):
                        return cand_repo

        # 2. Convention-based search in observation directory across all candidate base directories
        standard_filenames = [
            "rgb.jpg", "rgb.jpeg", "rgb.png", "rgb.webp",
            "visual.jpg", "visual.jpeg", "visual.png",
            "image.jpg", "image.jpeg", "image.png",
        ]

        for base_dir in unique_base_dirs:
            possible_dirs: List[Path] = []
            if scene_id:
                possible_dirs.append(base_dir / "water_bodies" / wb_id / "observations" / scene_id)
            possible_dirs.append(base_dir / "water_bodies" / wb_id / "observations" / str(observation.id))
            possible_dirs.append(base_dir / "water_bodies" / wb_id / str(observation.id))

            for d in possible_dirs:
                if not d.exists() or not d.is_dir():
                    continue
                if not cls._is_safe_path(d, base_dir):
                    continue

                for fname in standard_filenames:
                    test_file = d / fname
                    if cls._is_valid_image_file(test_file):
                        return test_file

                try:
                    for entry in d.iterdir():
                        if cls._is_valid_image_file(entry):
                            return entry
                except (OSError, PermissionError):
                    continue

        return None

    @classmethod
    def get_latest_visual_observation(
        cls,
        water_body_id: Any,
        db: Any,
        data_dir: Optional[Path] = None,
    ) -> Optional[Tuple[SatelliteObservation, Path]]:
        """
        Finds the newest observation for a water body that has a valid, verified local image.
        Sorts all observations by sensing_date descending, testing each until one with a valid
        image is found. Does NOT fail immediately on the newest observation.
        """
        # Defensive check for reversed parameters (db, water_body_id)
        if hasattr(water_body_id, "execute") and isinstance(db, str):
            water_body_id, db = db, water_body_id
        stmt = (
            select(SatelliteObservation)
            .where(SatelliteObservation.water_body_id == water_body_id)
            .order_by(SatelliteObservation.sensing_date.desc())
        )
        observations = db.execute(stmt).scalars().all()

        for obs in observations:
            resolved_path = cls.resolve_visual_image(obs, data_dir=data_dir)
            if resolved_path is not None:
                return (obs, resolved_path)

        return None
