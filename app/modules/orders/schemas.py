"""Schemas Pydantic del módulo de órdenes."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class ShippingAddressIn(BaseModel):
    """Dirección de envío que se guarda como snapshot en la orden."""

    recipient: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    line1: str = Field(min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str = Field(min_length=2, max_length=2)


class CheckoutRequest(BaseModel):
    shipping_address: ShippingAddressIn
    coupon_code: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=500)


class OrderItemOut(BaseModel):
    id: uuid.UUID
    variant_id: uuid.UUID | None
    product_id: uuid.UUID | None
    product_title: str
    variant_label: str | None
    sku: str
    currency: str
    unit_price: Decimal
    quantity: int
    line_total: Decimal
    commission_rate: Decimal
    commission_amount: Decimal


class SellerOrderOut(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    status: str
    currency: str
    subtotal: Decimal
    shipping_cost: Decimal
    discount_amount: Decimal
    commission_amount: Decimal
    payout_amount: Decimal
    items: list[OrderItemOut]


class OrderOut(BaseModel):
    """Orden completa con sus sub-órdenes por vendedor."""

    id: uuid.UUID
    order_number: str
    status: str
    payment_status: str
    currency: str
    subtotal: Decimal
    shipping_total: Decimal
    discount_total: Decimal
    total: Decimal
    shipping_address: dict[str, Any]
    notes: str | None
    created_at: datetime
    seller_orders: list[SellerOrderOut]


class OrderSummaryOut(BaseModel):
    """Resumen para el listado (sin líneas)."""

    id: uuid.UUID
    order_number: str
    status: str
    payment_status: str
    currency: str
    total: Decimal
    created_at: datetime


class OrderListOut(BaseModel):
    items: list[OrderSummaryOut]
    next_cursor: str | None


class SellerOrderSummaryOut(BaseModel):
    """Resumen de una venta (sub-orden) para el vendedor."""

    id: uuid.UUID
    order_id: uuid.UUID
    status: str
    currency: str
    subtotal: Decimal
    commission_amount: Decimal
    payout_amount: Decimal
    created_at: datetime


class SellerOrderListOut(BaseModel):
    items: list[SellerOrderSummaryOut]
    next_cursor: str | None
