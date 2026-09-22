"""Lógica de negocio del módulo de búsqueda."""

import base64
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import (
    Category,
    Product,
    ProductImage,
    ProductStatus,
    ProductVariant,
)
from app.modules.search.schemas import (
    BrandFacetOut,
    CategoryFacetOut,
    PriceFacetOut,
    ProductSearchItem,
    SearchFacetsOut,
    SearchResponse,
)
from app.modules.sellers.models import Store

# Cuántas opciones se devuelven por faceta (las más frecuentes).
FACET_LIMIT = 20


def _search_vector() -> Any:
    """Expresión tsvector sobre título + descripción + marca."""
    return func.to_tsvector(
        "simple",
        func.coalesce(Product.title, "")
        + " "
        + func.coalesce(Product.description, "")
        + " "
        + func.coalesce(Product.brand, ""),
    )


def _min_price_subquery() -> Any:
    """Subconsulta del precio mínimo entre las variantes del producto."""
    return (
        select(func.min(ProductVariant.price))
        .where(ProductVariant.product_id == Product.id)
        .scalar_subquery()
    )


def _thumbnail_subquery() -> Any:
    """Subconsulta de la primera imagen del producto."""
    return (
        select(ProductImage.object_key)
        .where(ProductImage.product_id == Product.id)
        .order_by(ProductImage.position)
        .limit(1)
        .scalar_subquery()
    )


def _store_name_subquery() -> Any:
    """Subconsulta del nombre de la tienda que vende el producto (sin duplicar filas por JOIN)."""
    return select(Store.name).where(Store.id == Product.store_id).scalar_subquery()


def _text_condition(vector: Any, q: str | None) -> Any | None:
    """Condición de texto (full-text + tolerante a errores), o `None` si no hay búsqueda."""
    if not q:
        return None
    return or_(
        vector.op("@@")(func.plainto_tsquery("simple", q)),
        Product.title.ilike(f"%{q}%"),
        func.similarity(Product.title, q) > 0.2,
    )


def _price_conditions(
    min_price_sq: Any, min_price: Decimal | None, max_price: Decimal | None
) -> list[Any]:
    """Condiciones de rango de precio sobre el precio mínimo de cada producto."""
    conditions: list[Any] = []
    if min_price is not None:
        conditions.append(min_price_sq >= min_price)
    if max_price is not None:
        conditions.append(min_price_sq <= max_price)
    return conditions


def _encode_cursor(sort_value: str, item_id: str) -> str:
    raw = f"{sort_value}|{item_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    value, item_id = raw.rsplit("|", 1)
    return value, item_id


def _parse_cursor_value(value: str, kind: str) -> Any:
    if kind == "datetime":
        return datetime.fromisoformat(value)
    if kind == "decimal":
        return Decimal(value)
    return float(value)


def _cursor_value(row: Any, kind: str) -> str:
    if kind == "datetime":
        return str(row["created_at"].isoformat())
    if kind == "decimal":
        return str(row["min_price"]) if row["min_price"] is not None else "0"
    return str(row["rank"])


class SearchService:
    """Búsqueda de productos activos con texto tolerante a errores y facetas.

    La lógica vive detrás de esta interfaz para poder migrar a Meilisearch/OpenSearch
    más adelante sin tocar la API.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        *,
        q: str | None,
        category_id: uuid.UUID | None,
        brand: str | None,
        min_price: Decimal | None,
        max_price: Decimal | None,
        sort: str,
        cursor: str | None,
        limit: int,
    ) -> SearchResponse:
        min_price_sq = _min_price_subquery()
        thumbnail_sq = _thumbnail_subquery()
        store_name_sq = _store_name_subquery()
        vector = _search_vector()
        rank = func.ts_rank(vector, func.plainto_tsquery("simple", q)) if q else None

        # Condiciones comunes: producto publicado y texto. Las facetas se cuentan con **los demás
        # filtros aplicados** y el suyo propio fuera, que es lo que espera la barra de filtros.
        base: list[Any] = [Product.status == ProductStatus.ACTIVE, Product.deleted_at.is_(None)]
        text = _text_condition(vector, q)
        if text is not None:
            base.append(text)

        category_filter: list[Any] = (
            [Product.category_id == category_id] if category_id is not None else []
        )
        brand_filter: list[Any] = [Product.brand == brand] if brand is not None else []
        price_filters = _price_conditions(min_price_sq, min_price, max_price)

        columns: list[Any] = [
            Product.id,
            Product.title,
            Product.slug,
            Product.brand,
            Product.category_id,
            Product.created_at,
            Product.rating_average,
            Product.rating_count.label("review_count"),
            min_price_sq.label("min_price"),
            thumbnail_sq.label("thumbnail"),
            store_name_sq.label("store_name"),
        ]
        if rank is not None:
            columns.append(rank.label("rank"))

        stmt: Any = select(*columns).where(*base, *category_filter, *brand_filter, *price_filters)

        # Ordenamiento
        if sort == "price_asc":
            order_expr: Any = min_price_sq
            descending = False
            kind = "decimal"
        elif sort == "price_desc":
            order_expr = min_price_sq
            descending = True
            kind = "decimal"
        elif sort == "relevance" and rank is not None:
            order_expr = rank
            descending = True
            kind = "float"
        else:
            order_expr = Product.created_at
            descending = True
            kind = "datetime"

        if cursor:
            sort_value_str, last_id_str = _decode_cursor(cursor)
            sort_value = _parse_cursor_value(sort_value_str, kind)
            last_id = uuid.UUID(last_id_str)
            if descending:
                stmt = stmt.where(
                    or_(
                        order_expr < sort_value,
                        (order_expr == sort_value) & (Product.id < last_id),
                    )
                )
            else:
                stmt = stmt.where(
                    or_(
                        order_expr > sort_value,
                        (order_expr == sort_value) & (Product.id > last_id),
                    )
                )

        stmt = stmt.order_by(
            desc(order_expr) if descending else asc(order_expr),
            desc(Product.id) if descending else asc(Product.id),
        ).limit(limit + 1)

        result = await self._session.execute(stmt)
        rows = list(result.mappings().all())

        has_more = len(rows) > limit
        rows = rows[:limit]

        items = [
            ProductSearchItem(
                id=row["id"],
                title=row["title"],
                slug=row["slug"],
                brand=row["brand"],
                category_id=row["category_id"],
                min_price=row["min_price"],
                thumbnail=row["thumbnail"],
                rating_average=row["rating_average"],
                review_count=int(row["review_count"] or 0),
                store_name=row["store_name"],
            )
            for row in rows
        ]

        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = _encode_cursor(_cursor_value(last, kind), str(last["id"]))

        # Facetas: cada una con los demás filtros aplicados y el suyo propio excluido.
        categories = await self._categories_facet([*base, *brand_filter, *price_filters])
        brands = await self._brands_facet([*base, *category_filter, *price_filters])
        price = await self._price_facet(
            min_price_sq, [*base, *category_filter, *brand_filter]
        )

        return SearchResponse(
            items=items,
            next_cursor=next_cursor,
            facets=SearchFacetsOut(categories=categories, brands=brands, price=price),
        )

    async def _categories_facet(self, conditions: list[Any]) -> list[CategoryFacetOut]:
        """Cuántos resultados hay por categoría (solo categorías con resultados)."""
        total = func.count(Product.id)
        stmt = (
            select(Product.category_id, Category.name, total)
            .join(Category, Category.id == Product.category_id)
            .where(*conditions, Category.deleted_at.is_(None))
            .group_by(Product.category_id, Category.name)
            .order_by(desc(total), Category.name)
            .limit(FACET_LIMIT)
        )
        rows = await self._session.execute(stmt)
        return [
            CategoryFacetOut(category_id=row[0], name=row[1], count=int(row[2])) for row in rows
        ]

    async def _brands_facet(self, conditions: list[Any]) -> list[BrandFacetOut]:
        """Cuántos resultados hay por marca (las marcas vacías no son una faceta)."""
        total = func.count(Product.id)
        stmt = (
            select(Product.brand, total)
            .where(*conditions, Product.brand.is_not(None), Product.brand != "")
            .group_by(Product.brand)
            .order_by(desc(total), Product.brand)
            .limit(FACET_LIMIT)
        )
        rows = await self._session.execute(stmt)
        return [BrandFacetOut(brand=row[0], count=int(row[1])) for row in rows]

    async def _price_facet(self, min_price_sq: Any, conditions: list[Any]) -> PriceFacetOut:
        """Precio mínimo y máximo de los resultados (sin el filtro de precio aplicado)."""
        row = (
            await self._session.execute(
                select(func.min(min_price_sq), func.max(min_price_sq)).where(*conditions)
            )
        ).one()
        return PriceFacetOut(min=row[0], max=row[1])

    async def suggest(self, q: str, limit: int) -> list[str]:
        """Sugiere títulos de productos activos que coinciden con el texto."""
        stmt: Any = (
            select(Product.title)
            .where(Product.status == ProductStatus.ACTIVE, Product.deleted_at.is_(None))
            .where(or_(Product.title.ilike(f"%{q}%"), func.similarity(Product.title, q) > 0.2))
            .order_by(func.similarity(Product.title, q).desc())
            .limit(limit * 2)
        )
        result = await self._session.execute(stmt)
        titles = list(result.scalars().all())

        seen: set[str] = set()
        unique: list[str] = []
        for title in titles:
            if title not in seen:
                seen.add(title)
                unique.append(title)
            if len(unique) >= limit:
                break
        return unique
