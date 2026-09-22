"""Schemas Pydantic del módulo de envíos."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ShipmentCreate(BaseModel):
    """Datos que aporta el vendedor al preparar el envío."""

    carrier: str | None = Field(default=None, max_length=80)
    tracking_number: str | None = Field(default=None, max_length=120)
    tracking_url: str | None = Field(default=None, max_length=500)
    cost: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str | None = Field(default=None, max_length=500)


class ShipmentUpdate(BaseModel):
    carrier: str | None = Field(default=None, max_length=80)
    tracking_number: str | None = Field(default=None, max_length=120)
    tracking_url: str | None = Field(default=None, max_length=500)
    cost: Decimal | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=500)


class ShipmentEventOut(BaseModel):
    status: str
    description: str | None
    occurred_at: datetime


class ShipmentOut(BaseModel):
    id: uuid.UUID
    seller_order_id: uuid.UUID
    store_id: uuid.UUID
    status: str
    carrier: str | None
    tracking_number: str | None
    tracking_url: str | None
    cost: Decimal
    currency: str
    notes: str | None
    shipped_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    events: list[ShipmentEventOut]
