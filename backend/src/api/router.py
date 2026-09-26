from fastapi import APIRouter

from api.routes import health, runs

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(runs.router)
