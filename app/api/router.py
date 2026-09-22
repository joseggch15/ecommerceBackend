"""Router principal que agrupa todos los routers de la API v1."""

from fastapi import APIRouter

from app.api.v1 import health
from app.modules.identity import api as identity_api

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health")
api_router.include_router(identity_api.router)
