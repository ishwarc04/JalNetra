"""
Map and Raster Visualization REST API router for JalNetra.
Provides vector GeoJSON layers, scene footprint layers, raster metadata, and RGB visualization images.
"""
from typing import Dict, Any, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.map_service import MapService
from app.services.raster.service import RasterService
from app.services.raster.models import (
    SceneRasterMetadataResponse,
    RGBVisualizationResponse,
)

router = APIRouter(prefix="/map", tags=["Interactive Map & Raster Visualization"])

map_service = MapService()
raster_service = RasterService()


def parse_and_validate_bbox(bbox_str: Optional[str]) -> Optional[Tuple[float, float, float, float]]:
    """Validates and parses comma-separated bounding box 'west,south,east,north'."""
    if not bbox_str:
        return None
    try:
        parts = [float(p.strip()) for p in bbox_str.split(",")]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bounding box must be comma-separated numeric coordinates: west,south,east,north",
        )
    if len(parts) != 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bounding box must contain exactly 4 coordinates: west,south,east,north",
        )
    w, s, e, n = parts
    if not (-180.0 <= w <= 180.0 and -180.0 <= e <= 180.0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Longitude coordinates must be within [-180, 180]",
        )
    if not (-90.0 <= s <= 90.0 and -90.0 <= n <= 90.0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Latitude coordinates must be within [-90, 90]",
        )
    if w >= e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="West coordinate must be less than East coordinate",
        )
    if s >= n:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="South coordinate must be less than North coordinate",
        )
    return (w, s, e, n)


def validate_padding_percent(padding_pct: Optional[float]) -> Optional[float]:
    """Validates padding percentage is between 0 and 100."""
    if padding_pct is None:
        return None
    if padding_pct < 0.0 or padding_pct > 100.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Padding percentage must be between 0 and 100",
        )
    return padding_pct


@router.get(
    "/water-bodies/geojson",
    summary="Get all water bodies as GeoJSON FeatureCollection",
    response_model=Dict[str, Any],
)
def get_water_bodies_geojson(db: Session = Depends(get_db)):
    """Returns all active water body geometries in GeoJSON format for the map layer."""
    return map_service.get_water_bodies_geojson(db)


@router.get(
    "/scenes",
    summary="List registered satellite scenes for mapping",
    response_model=List[Dict[str, Any]],
)
def get_map_scenes(
    water_body_id: str = Query(..., description="Target water body UUID"),
    db: Session = Depends(get_db),
):
    """Returns registered satellite scenes with footprints and asset status for a water body."""
    return map_service.get_scenes_for_water_body(db, water_body_id)


@router.get(
    "/scenes/{scene_id}/metadata",
    summary="Get raster metadata and geographic bounds for a scene",
    response_model=SceneRasterMetadataResponse,
)
def get_scene_raster_metadata(scene_id: str, db: Session = Depends(get_db)):
    """
    Inspects CRS, dimensions, resolution, and geographic bounds of downloaded GeoTIFFs.
    Never exposes internal filesystem paths.
    """
    try:
        return raster_service.get_scene_metadata(db, scene_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to inspect raster: {str(e)}")


@router.get(
    "/scenes/{scene_id}/rgb",
    summary="Get RGB visualization metadata and display bounds",
    response_model=RGBVisualizationResponse,
)
def get_scene_rgb_visualization(
    scene_id: str,
    water_body_id: Optional[str] = Query(None, description="Optional water body UUID to crop and focus RGB raster"),
    bbox: Optional[str] = Query(None, description="Optional custom bounding box 'west,south,east,north'"),
    padding_percent: Optional[float] = Query(None, description="Optional custom padding percentage for water body crop (0-100)"),
    force_regenerate: bool = Query(False, description="Force re-rendering even if cached"),
    db: Session = Depends(get_db),
):
    """
    Aligns and reprojects B04, B03, B02 GeoTIFF bands, applies percentile contrast stretch,
    optionally crops to the target water body's extent + padding or custom AOI bounding box,
    and returns geographic bounds and image URL for Leaflet ImageOverlay.
    """
    crop_bbox = parse_and_validate_bbox(bbox)
    pad_val = validate_padding_percent(padding_percent)

    try:
        return raster_service.get_or_render_rgb(
            db,
            scene_id,
            water_body_id=water_body_id,
            crop_bbox=crop_bbox,
            padding_percent=pad_val,
            force_regenerate=force_regenerate,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Raster processing failed: {str(e)}")


@router.get(
    "/scenes/{scene_id}/rgb/image",
    summary="Get raw RGB visualization PNG image for Leaflet overlay",
)
def get_scene_rgb_image(
    scene_id: str,
    water_body_id: Optional[str] = Query(None, description="Optional water body UUID for focused crop image"),
    bbox: Optional[str] = Query(None, description="Optional custom bounding box 'west,south,east,north'"),
    padding_percent: Optional[float] = Query(None, description="Optional custom padding percentage for water body crop (0-100)"),
    db: Session = Depends(get_db),
):
    """
    Safely streams the rendered RGBA PNG image for the scene.
    Validates scene ID against the database to prevent path traversal.
    """
    crop_bbox = parse_and_validate_bbox(bbox)
    pad_val = validate_padding_percent(padding_percent)

    try:
        img_path = raster_service.get_rgb_image_path(
            db,
            scene_id,
            water_body_id=water_body_id,
            crop_bbox=crop_bbox,
            padding_percent=pad_val,
        )
        return FileResponse(
            path=img_path,
            media_type="image/png",
            filename=img_path.name,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to serve raster image: {str(e)}")
