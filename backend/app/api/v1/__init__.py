from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.water_bodies import router as water_bodies_router
from app.api.v1.storage import router as storage_router
from app.api.v1.discovery import router as discovery_router
from app.api.v1.satellite import router as satellite_router
from app.api.v1.map import router as map_router
from app.api.v1.processing import router as processing_router
from app.api.v1.visual_data import router as visual_data_router
from app.api.v1.analysis import router as analysis_router
from app.api.v1.spectral import router as spectral_router
from app.api.v1.ai import router as ai_router
from app.api.v1.telegram import router as telegram_router
from app.api.v1.weather import router as weather_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(water_bodies_router)
api_v1_router.include_router(storage_router)
api_v1_router.include_router(discovery_router)
api_v1_router.include_router(satellite_router)
api_v1_router.include_router(map_router)
api_v1_router.include_router(processing_router)
api_v1_router.include_router(visual_data_router)
api_v1_router.include_router(analysis_router)
api_v1_router.include_router(spectral_router)
api_v1_router.include_router(ai_router)
api_v1_router.include_router(telegram_router)
api_v1_router.include_router(weather_router)

