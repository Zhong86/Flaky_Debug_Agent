from fastapi import APIRouter

from api.routes import health, runs, webhooks

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(runs.router)
api_router.include_router(webhooks.router)
