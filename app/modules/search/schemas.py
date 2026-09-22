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
    # Reputación del producto (agregados que mantiene el módulo de reseñas).
    rating_average: Decimal | None
    review_count: int
    # Tienda que lo vende (para «vendido por»).
    store_name: str
    # Unidades vendidas en órdenes pagadas (insignia «más vendido»).
    sold_count: int


class CategoryFacetOut(BaseModel):
    """Cuántos resultados hay en una categoría."""

    category_id: uuid.UUID
    name: str
    count: int


class BrandFacetOut(BaseModel):
    """Cuántos resultados hay de una marca."""

    brand: str
    count: int


class PriceFacetOut(BaseModel):
    """Precio mínimo y máximo **reales** de los resultados (para el deslizador de precio).

    No se inventan tramos: el frontend decide cómo agruparlos con datos reales.
    """

    min: Decimal | None
    max: Decimal | None


class SearchFacetsOut(BaseModel):
    """Conteos para la barra de filtros.

    Cada faceta se cuenta con **los demás filtros aplicados** y el suyo propio excluido: así al
    usuario le sale cuántos resultados tendría al añadir esa opción.
    """

    categories: list[CategoryFacetOut]
    brands: list[BrandFacetOut]
    price: PriceFacetOut


class SearchResponse(BaseModel):
    items: list[ProductSearchItem]
    next_cursor: str | None
    facets: SearchFacetsOut

