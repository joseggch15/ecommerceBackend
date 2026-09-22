"""Router principal que agrupa todos los routers de la API v1."""

from fastapi import APIRouter

from app.api.v1 import health
from app.modules.catalog import api as catalog_api
from app.modules.currency import api as currency_api
from app.modules.identity import api as identity_api
from app.modules.inventory import api as inventory_api
from app.modules.search import api as search_api
from app.modules.sellers import api as sellers_api

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health")
api_router.include_router(identity_api.router)
api_router.include_router(sellers_api.router)
api_router.include_router(catalog_api.router)
api_router.include_router(inventory_api.router)
api_router.include_router(search_api.router)
api_router.include_router(currency_api.router)
