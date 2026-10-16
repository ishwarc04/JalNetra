from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.water_body import WaterBodyRead
from app.services.discovery import (
    WaterBodyDiscoveryService,
    WaterBodyDiscoveryResult,
    DiscoverySearchResponse,
    ProviderListResponse,
    ProviderStatus,
    LocationSearchResponse,
    AreaDiscoveryResponse,
    BatchImportRequest,
    BatchImportResponse,
)

router = APIRouter(prefix="/discovery", tags=["Discovery"])


def get_discovery_service(db: Session = Depends(get_db)) -> WaterBodyDiscoveryService:
    return WaterBodyDiscoveryService(db)


@router.get(
    "/location/search",
    response_model=LocationSearchResponse,
    summary="Geocode user-entered location (city, town, place)",
    description="Resolves location query into coordinates using OpenStreetMap Nominatim with local caching.",
)
async def search_location(
    q: str = Query(..., min_length=1, max_length=100, description="Location search query (e.g. Delhi, Pune)"),
    limit: int = Query(5, ge=1, le=10, description="Result limit (max 10)"),
    provider: Optional[str] = Query(None, description="Geocoding provider (default: osm)"),
    service: WaterBodyDiscoveryService = Depends(get_discovery_service),
) -> LocationSearchResponse:
    return await service.geocode_location(query=q, limit=limit, provider_name=provider)


@router.get(
    "/water-bodies/area",
    response_model=AreaDiscoveryResponse,
    summary="Discover water bodies within a radius of coordinates",
    description="Finds lakes, reservoirs, ponds, and rivers within the specified radius (km) of given coordinates.",
)
async def discover_water_bodies_by_area(
    latitude: float = Query(..., ge=-90.0, le=90.0, description="Center latitude in degrees"),
    longitude: float = Query(..., ge=-180.0, le=180.0, description="Center longitude in degrees"),
    radius_km: float = Query(1.0, ge=0.1, le=50.0, description="Search radius in kilometers"),
    limit: int = Query(30, ge=1, le=60, description="Result limit (max 60)"),
    query_location: Optional[str] = Query(None, description="Optional label for the searched location"),
    provider: Optional[str] = Query(None, description="Discovery provider (default: osm)"),
    service: WaterBodyDiscoveryService = Depends(get_discovery_service),
) -> AreaDiscoveryResponse:
    return await service.search_area(
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        limit=limit,
        query_location=query_location,
        provider_name=provider,
    )


@router.get(
    "/providers",
    response_model=ProviderListResponse,
    summary="List available water body geographic data providers",
)
def list_discovery_providers(
    service: WaterBodyDiscoveryService = Depends(get_discovery_service),
) -> ProviderListResponse:
    providers = service.list_providers()
    return ProviderListResponse(providers=providers)


@router.get(
    "/water-bodies/search",
    response_model=DiscoverySearchResponse,
    summary="Search global water bodies from geographic provider",
)
async def search_water_bodies(
    q: str = Query(..., min_length=1, max_length=100, description="Search query string"),
    limit: int = Query(10, ge=1, le=20, description="Result limit (max 20)"),
    provider: Optional[str] = Query(None, description="Target provider (default: osm)"),
    service: WaterBodyDiscoveryService = Depends(get_discovery_service),
) -> DiscoverySearchResponse:
    return await service.search(query=q, limit=limit, provider_name=provider)


@router.post(
    "/water-bodies/import",
    response_model=WaterBodyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Import a discovered water body into local SQLite catalog",
)
def import_water_body(
    payload: WaterBodyDiscoveryResult,
    service: WaterBodyDiscoveryService = Depends(get_discovery_service),
) -> WaterBodyRead:
    return service.import_water_body(payload)


@router.post(
    "/water-bodies/import-batch",
    response_model=BatchImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch import multiple discovered water bodies into local catalog",
    description="Idempotently registers a list of discovered water bodies into the local SQLite database.",
)
def import_water_bodies_batch(
    payload: BatchImportRequest,
    service: WaterBodyDiscoveryService = Depends(get_discovery_service),
) -> BatchImportResponse:
    return service.import_water_bodies_batch(payload)

