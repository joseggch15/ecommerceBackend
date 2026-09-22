"""Modelos ORM del módulo de vendedores."""

import enum
import uuid
from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.base import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, enum_values


class StoreStatus(enum.StrEnum):
    """Estado de la tienda del vendedor."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class Store(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Tienda de un vendedor (un usuario tiene como máximo una tienda)."""

    __tablename__ = "stores"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[StoreStatus] = mapped_column(
        Enum(StoreStatus, name="store_status", native_enum=False, values_callable=enum_values),
        nullable=False,
        default=StoreStatus.PENDING,
    )
    # Reputación (agregados denormalizados que mantiene el módulo de reseñas).
    rating_average: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    rating_count: Mapped[int] = mapped_column(default=0, nullable=False)
