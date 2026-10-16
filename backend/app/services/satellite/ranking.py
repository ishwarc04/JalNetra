import math
from datetime import datetime, timezone
from typing import Dict, List, Optional
from app.services.satellite.models import NormalizedScene


def compute_bbox_intersection_ratio(
    bbox1: Optional[List[float]],
    bbox2: Optional[List[float]],
) -> float:
    """
    Computes approximate intersection-over-union or overlap ratio between two [min_lon, min_lat, max_lon, max_lat] boxes.
    Returns 0.0 to 1.0.
    """
    if not bbox1 or not bbox2 or len(bbox1) < 4 or len(bbox2) < 4:
        return 0.5  # Neutral overlap score if bounding box missing

    min_lon1, min_lat1, max_lon1, max_lat1 = bbox1[:4]
    min_lon2, min_lat2, max_lon2, max_lat2 = bbox2[:4]

    # Intersection rectangle
    inter_min_lon = max(min_lon1, min_lon2)
    inter_min_lat = max(min_lat1, min_lat2)
    inter_max_lon = min(max_lon1, max_lon2)
    inter_max_lat = min(max_lat1, max_lat2)

    if inter_min_lon >= inter_max_lon or inter_min_lat >= inter_max_lat:
        return 0.0

    inter_area = (inter_max_lon - inter_min_lon) * (inter_max_lat - inter_min_lat)
    target_area = (max_lon1 - min_lon1) * (max_lat1 - min_lat1)

    if target_area <= 0:
        return 0.5

    return min(max(inter_area / target_area, 0.0), 1.0)


def rank_and_score_scenes(
    scenes: List[NormalizedScene],
    target_bbox: Optional[List[float]] = None,
) -> List[NormalizedScene]:
    """
    Ranks satellite scenes deterministically prioritizing:
    1. Low cloud cover (weight: 0.5)
    2. Spatial overlap with target water body (weight: 0.3)
    3. Sensing recency (weight: 0.2)
    """
    if not scenes:
        return []

    now = datetime.now(timezone.utc)

    # Find earliest and latest dates for relative normalization
    timestamps = [s.sensing_start.timestamp() for s in scenes]
    min_ts = min(timestamps)
    max_ts = max(timestamps)
    ts_span = max(max_ts - min_ts, 1.0)

    for scene in scenes:
        # 1. Cloud score: 100% cloud -> 0.0, 0% cloud -> 1.0
        cloud = scene.cloud_cover_percent if scene.cloud_cover_percent is not None else 50.0
        cloud_score = max(0.0, 1.0 - (cloud / 100.0))

        # 2. Overlap score: 0.0 to 1.0
        overlap_score = compute_bbox_intersection_ratio(target_bbox, scene.bbox)

        # 3. Recency score: 0.0 (oldest in batch) to 1.0 (most recent in batch)
        recency_score = (scene.sensing_start.timestamp() - min_ts) / ts_span

        # Weighted composite score (0.0 to 100.0)
        total_score = (cloud_score * 50.0) + (overlap_score * 30.0) + (recency_score * 20.0)
        scene.score = round(total_score, 2)

    # Sort descending by score
    scenes.sort(key=lambda s: (s.score or 0.0), reverse=True)
    return scenes
