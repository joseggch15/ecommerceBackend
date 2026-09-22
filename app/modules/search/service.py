"""Lógica de negocio del módulo de búsqueda."""

import base64
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Product, ProductImage, ProductStatus, ProductVariant
from app.modules.search.schemas import ProductSearchItem, SearchResponse


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
        vector = _search_vector()
        rank = func.ts_rank(vector, func.plainto_tsquery("simple", q)) if q else None

        columns: list[Any] = [
            Product.id,
            Product.title,
            Product.slug,
            Product.brand,
            Product.category_id,
            Product.created_at,
            min_price_sq.label("min_price"),
            thumbnail_sq.label("thumbnail"),
        ]
        if rank is not None:
            columns.append(rank.label("rank"))

        stmt: Any = select(*columns).where(
            Product.status == ProductStatus.ACTIVE, Product.deleted_at.is_(None)
        )

        if q:
            stmt = stmt.where(
                or_(
                    vector.op("@@")(func.plainto_tsquery("simple", q)),
                    Product.title.ilike(f"%{q}%"),
                    func.similarity(Product.title, q) > 0.2,
                )
            )

        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        if brand is not None:
            stmt = stmt.where(Product.brand == brand)
        if min_price is not None:
            stmt = stmt.where(min_price_sq >= min_price)
        if max_price is not None:
            stmt = stmt.where(min_price_sq <= max_price)

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
            )
            for row in rows
        ]

        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = _encode_cursor(_cursor_value(last, kind), str(last["id"]))

        return SearchResponse(items=items, next_cursor=next_cursor)

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
