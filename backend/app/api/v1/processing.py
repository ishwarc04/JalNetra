"""
Processing REST API router for JalNetra (Phase 5).
Endpoints for triggering cloud masking & spectral water segmentation, inspecting metadata,
and serving georeferenced raster mask visualization overlays.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.processing.service import ProcessingService
from app.services.processing.water_detection import DEFAULT_WATER_THRESHOLD
from app.services.processing.models import (
    ProcessingStatusResponse,
    MaskVisualizationResponse,
)

router = APIRouter(prefix="/processing", tags=["Preprocessing: Cloud Masking & Water Detection"])

processing_service = ProcessingService()


@router.post(
    "/scenes/{scene_id}",
    summary="Run cloud masking and water detection for a scene",
    response_model=ProcessingStatusResponse,
)
def run_scene_processing(
    scene_id: str,
    threshold: float = Query(DEFAULT_WATER_THRESHOLD, description="Spectral water detection threshold"),
    force_recompute: bool = Query(False, description="Force recalculation even if cached"),
    db: Session = Depends(get_db),
):
    """
    Synchronously generates:
    1. SCL-based binary valid pixel / cloud-shadow mask (cloud_mask.tif)
    2. Deterministic spectral water segmentation mask (water_mask.tif)
    3. Processing metrics & statistics (processing_metadata.json)
    4. Georeferenced visualization overlays for Leaflet ImageOverlay
    """
    try:
        return processing_service.process_scene(
            db=db,
            scene_id=scene_id,
            threshold=threshold,
            force_recompute=force_recompute,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Processing failed: {str(e)}")


@router.get(
    "/scenes/{scene_id}",
    summary="Get processing status and metrics for a scene",
    response_model=ProcessingStatusResponse,
)
def get_scene_processing_status(
    scene_id: str,
    db: Session = Depends(get_db),
):
    """Returns cloud mask and water detection availability, metrics, and band status."""
    try:
        return processing_service.get_processing_status(db=db, scene_id=scene_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


from app.api.v1.map import parse_and_validate_bbox, validate_padding_percent


@router.get(
    "/scenes/{scene_id}/cloud-mask",
    summary="Get cloud mask visualization bounds and image URL",
    response_model=MaskVisualizationResponse,
)
def get_cloud_mask_visualization(
    scene_id: str,
    water_body_id: Optional[str] = Query(None, description="Optional water body UUID to crop mask"),
    bbox: Optional[str] = Query(None, description="Optional bounding box 'west,south,east,north'"),
    padding_percent: Optional[float] = Query(None, description="Optional padding percent"),
    db: Session = Depends(get_db),
):
    """Returns geographic display bounds (EPSG:4326) and image overlay URL for the cloud/shadow mask."""
    crop_bbox = parse_and_validate_bbox(bbox)
    pad_val = validate_padding_percent(padding_percent)
    try:
        return processing_service.get_mask_visualization(
            db=db,
            scene_id=scene_id,
            mask_type="cloud_mask",
            water_body_id=water_body_id,
            crop_bbox=crop_bbox,
            padding_percent=pad_val,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/scenes/{scene_id}/cloud-mask/image",
    summary="Stream raw cloud mask PNG overlay",
)
def get_cloud_mask_image(
    scene_id: str,
    water_body_id: Optional[str] = Query(None, description="Optional water body UUID"),
    bbox: Optional[str] = Query(None, description="Optional bounding box 'west,south,east,north'"),
    padding_percent: Optional[float] = Query(None, description="Optional padding percent"),
    db: Session = Depends(get_db),
):
    """Streams the rendered semi-transparent amber cloud/shadow PNG image overlay for Leaflet."""
    crop_bbox = parse_and_validate_bbox(bbox)
    pad_val = validate_padding_percent(padding_percent)
    try:
        img_path = processing_service.get_mask_image_path(
            db=db,
            scene_id=scene_id,
            mask_type="cloud_mask",
            water_body_id=water_body_id,
            crop_bbox=crop_bbox,
            padding_percent=pad_val,
        )
        return FileResponse(
            path=img_path,
            media_type="image/png",
            filename=f"scene_{scene_id}_cloud_mask.png",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/scenes/{scene_id}/water-mask",
    summary="Get water mask visualization bounds and image URL",
    response_model=MaskVisualizationResponse,
)
def get_water_mask_visualization(
    scene_id: str,
    water_body_id: Optional[str] = Query(None, description="Optional water body UUID to crop mask"),
    bbox: Optional[str] = Query(None, description="Optional bounding box 'west,south,east,north'"),
    padding_percent: Optional[float] = Query(None, description="Optional padding percent"),
    db: Session = Depends(get_db),
):
    """Returns geographic display bounds (EPSG:4326) and image overlay URL for the detected water mask."""
    crop_bbox = parse_and_validate_bbox(bbox)
    pad_val = validate_padding_percent(padding_percent)
    try:
        return processing_service.get_mask_visualization(
            db=db,
            scene_id=scene_id,
            mask_type="water_mask",
            water_body_id=water_body_id,
            crop_bbox=crop_bbox,
            padding_percent=pad_val,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/scenes/{scene_id}/water-mask/image",
    summary="Stream raw water mask PNG overlay",
)
def get_water_mask_image(
    scene_id: str,
    water_body_id: Optional[str] = Query(None, description="Optional water body UUID"),
    bbox: Optional[str] = Query(None, description="Optional bounding box 'west,south,east,north'"),
    padding_percent: Optional[float] = Query(None, description="Optional padding percent"),
    db: Session = Depends(get_db),
):
    """Streams the rendered semi-transparent cyan detected water PNG image overlay for Leaflet."""
    crop_bbox = parse_and_validate_bbox(bbox)
    pad_val = validate_padding_percent(padding_percent)
    try:
        img_path = processing_service.get_mask_image_path(
            db=db,
            scene_id=scene_id,
            mask_type="water_mask",
            water_body_id=water_body_id,
            crop_bbox=crop_bbox,
            padding_percent=pad_val,
        )
        return FileResponse(
            path=img_path,
            media_type="image/png",
            filename=f"scene_{scene_id}_water_mask.png",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
