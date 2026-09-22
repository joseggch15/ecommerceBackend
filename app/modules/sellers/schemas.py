"""Schemas Pydantic del módulo de vendedores."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.sellers.models import StoreStatus


class StoreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class StoreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class StoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    logo_url: str | None
    status: StoreStatus
    created_at: datetime


class PublicStoreOut(BaseModel):
    """Datos públicos de una tienda: los que puede ver cualquier visitante, sin sesión.

    No incluye `user_id` ni `status`: al comprador no le dicen nada y son datos internos.
    """

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    logo_url: str | None
    rating_average: Decimal | None
    rating_count: int
    orders_delivered: int
    created_at: datetime
