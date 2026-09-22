"""Endpoints del módulo de búsqueda."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.search.schemas import SearchResponse
from app.modules.search.service import SearchService

router = APIRouter(tags=["search"])


def get_search_service(session: AsyncSession = Depends(get_session)) -> SearchService:
    return SearchService(session)


@router.get("/catalog/search", response_model=SearchResponse)
async def search(
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    brand: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    sort: str = Query(default="newest", pattern="^(newest|price_asc|price_desc|relevance)$"),
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    service: SearchService = Depends(get_search_service),
) -> SearchResponse:
    """Busca productos activos por texto (tolerante a errores) y filtros por facetas."""
    return await service.search(
        q=q,
        category_id=category_id,
        brand=brand,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )


@router.get("/catalog/search/suggest", response_model=list[str])
async def suggest(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=10, ge=1, le=20),
    service: SearchService = Depends(get_search_service),
) -> list[str]:
    """Sugiere títulos de productos (autocompletado)."""
    return await service.suggest(q, limit)
