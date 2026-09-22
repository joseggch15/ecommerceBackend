"""Schemas Pydantic del módulo de carrito."""

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.catalog.schemas import VariantValueOut


class CartItemAdd(BaseModel):
    variant_id: uuid.UUID
    quantity: int = Field(default=1, gt=0, le=100)


class CartItemUpdate(BaseModel):
    quantity: int = Field(gt=0, le=100)


class CartItemOut(BaseModel):
    """Línea del carrito con los datos del producto al momento de mostrarlo."""

    variant_id: uuid.UUID
    sku: str
    product_id: uuid.UUID
    product_title: str
    product_slug: str
    store_id: uuid.UUID
    unit_price: Decimal
    quantity: int
    subtotal: Decimal
    # Unidades que se pueden comprar ahora mismo (0 = agotado). El servidor nunca deja añadir más
    # de las disponibles, pero el stock puede cambiar después de añadir.
    available: int = 0
    # Precio que tenía la variante cuando se añadió (None en líneas antiguas) y si ha cambiado.
    added_unit_price: Decimal | None = None
    price_changed: bool = False
    # Primera imagen y atributos de la variante (color, talla) para pintar la línea completa.
    thumbnail: str | None = None
    attribute_values: list[VariantValueOut] = Field(default_factory=list)


class CartOut(BaseModel):
    items: list[CartItemOut]
    total_items: int
    subtotal: Decimal
    currency: str
