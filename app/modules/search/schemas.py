"""Schemas Pydantic del módulo de búsqueda."""

import uuid
from decimal import Decimal

from pydantic import BaseModel


class ProductSearchItem(BaseModel):
    """Resultado de búsqueda de un producto."""

    id: uuid.UUID
    title: str
    slug: str
    brand: str | None
    category_id: uuid.UUID
    min_price: Decimal | None
    thumbnail: str | None


class SearchResponse(BaseModel):
    items: list[ProductSearchItem]
    next_cursor: str | None
