"""Schemas Pydantic del módulo de administración."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class ModerationIn(BaseModel):
    """Motivo opcional de la acción de moderación."""

    reason: str | None = Field(default=None, max_length=500)


class AdminActionOut(BaseModel):
    """Entrada del libro de auditoría."""

    id: uuid.UUID
    admin_user_id: uuid.UUID
    action: str
    target_type: str
    target_id: uuid.UUID | None
    reason: str | None
    data: dict[str, Any]
    created_at: datetime


class StoreSalesOut(BaseModel):
    store_id: uuid.UUID
    sales: Decimal


class MetricsOut(BaseModel):
    """Tablero de administración."""

    users: int
    stores: int
    products: int
    orders_by_status: dict[str, int]
    gmv: Decimal
    commission: Decimal
    top_stores: list[StoreSalesOut]
