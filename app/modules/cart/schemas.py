"""Schemas Pydantic del módulo de carrito."""

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


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


class CartOut(BaseModel):
    items: list[CartItemOut]
    total_items: int
    subtotal: Decimal
    currency: str
