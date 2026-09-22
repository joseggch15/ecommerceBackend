"""Schemas Pydantic del módulo de administración."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.modules.identity.models import UserRole
from app.modules.sellers.models import StoreStatus


class ModerationIn(BaseModel):
    """Motivo opcional de la acción de moderación."""

    reason: str | None = Field(default=None, max_length=500)


class AdminUserOut(BaseModel):
    """Usuario en el listado del panel de administración.

    **Nunca** sale de aquí el hash de la contraseña ni ningún token: esos datos ni siquiera se
    consultan en la base de datos (`AdminUserRepository`). Los campos de tienda van en `None` si
    la cuenta no tiene tienda (un comprador puro) y, si la tiene, es porque vende.
    """

    id: uuid.UUID
    email: EmailStr
    role: UserRole
    email_verified: bool
    full_name: str | None = None
    store_id: uuid.UUID | None = None
    store_name: str | None = None
    store_status: StoreStatus | None = None
    created_at: datetime


class AdminUserListOut(BaseModel):
    """Página del directorio de usuarios (paginación por cursor)."""

    items: list[AdminUserOut]
    next_cursor: str | None


class AdminQuestionOut(BaseModel):
    """Pregunta vista por el administrador (con el producto al que pertenece)."""

    id: uuid.UUID
    product_id: uuid.UUID
    product_title: str | None
    user_id: uuid.UUID
    body: str
    is_published: bool
    answer_count: int
    created_at: datetime


class AdminQuestionListOut(BaseModel):
    """Página de preguntas para moderar (paginación por cursor)."""

    items: list[AdminQuestionOut]
    next_cursor: str | None


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
