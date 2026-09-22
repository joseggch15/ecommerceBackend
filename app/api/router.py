"""Router principal que agrupa todos los routers de la API v1."""

from fastapi import APIRouter

from app.api.v1 import health
from app.modules.cart import api as cart_api
from app.modules.catalog import api as catalog_api
from app.modules.currency import api as currency_api
from app.modules.identity import api as identity_api
from app.modules.inventory import api as inventory_api
from app.modules.orders import api as orders_api
from app.modules.payments import api as payments_api
from app.modules.search import api as search_api
from app.modules.sellers import api as sellers_api
from app.modules.shipping import api as shipping_api

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health")
api_router.include_router(identity_api.router)
api_router.include_router(sellers_api.router)
api_router.include_router(catalog_api.router)
api_router.include_router(inventory_api.router)
api_router.include_router(search_api.router)
api_router.include_router(currency_api.router)
api_router.include_router(cart_api.router)
api_router.include_router(orders_api.router)
api_router.include_router(payments_api.router)
api_router.include_router(shipping_api.router)
