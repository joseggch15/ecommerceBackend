"""Schemas Pydantic del módulo de promociones."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.modules.promotions.models import DiscountType


class CouponCreate(BaseModel):
    """Creación de un cupón (solo admin)."""

    code: str = Field(min_length=3, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    discount_type: DiscountType
    value: Decimal = Field(gt=0)
    min_purchase: Decimal = Field(default=Decimal("0"), ge=0)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1)
    max_uses_per_user: int | None = Field(default=None, ge=1)
    store_id: uuid.UUID | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class CouponOut(BaseModel):
    id: uuid.UUID
    code: str
    description: str | None
    discount_type: str
    value: Decimal
    currency: str
    min_purchase: Decimal
    starts_at: datetime | None
    ends_at: datetime | None
    max_uses: int | None
    max_uses_per_user: int | None
    used_count: int
    store_id: uuid.UUID | None
    is_active: bool
    created_at: datetime


class CouponListOut(BaseModel):
    items: list[CouponOut]


class CouponValidateIn(BaseModel):
    code: str = Field(min_length=3, max_length=40)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class CouponValidateOut(BaseModel):
    """Vista previa del descuento sobre el carrito del usuario."""

    code: str
    discount_type: str
    discount_amount: Decimal
    subtotal: Decimal
    total: Decimal
    currency: str
