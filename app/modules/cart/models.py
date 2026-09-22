"""Modelos ORM del módulo de carrito (solo usuarios registrados)."""

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.base import TimestampMixin, UUIDPrimaryKeyMixin


class Cart(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Carrito persistente de un usuario registrado (uno por usuario)."""

    __tablename__ = "carts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )


class CartItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Línea del carrito: variante + cantidad (una por variante y carrito)."""

    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("cart_id", "variant_id", name="uq_cart_variant"),)

    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("carts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Precio de la variante **cuando se añadió** la línea: sirve para avisar al comprador de que el
    # precio ha cambiado desde entonces. Puede faltar en líneas antiguas (se añadieron antes de esta
    # columna), y en ese caso no se avisa de nada.
    unit_price_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
