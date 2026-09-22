"""Modelos ORM del módulo de inventario."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.base import TimestampMixin, UUIDPrimaryKeyMixin


class InventoryItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Stock disponible y reservado de una variante."""

    __tablename__ = "inventory_items"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(default=0, nullable=False)
    reserved_quantity: Mapped[int] = mapped_column(default=0, nullable=False)

    @property
    def available(self) -> int:
        """Stock disponible para vender (quantity - reserved)."""
        return self.quantity - self.reserved_quantity


class InventoryMovement(UUIDPrimaryKeyMixin, Base):
    """Movimiento del ledger de stock (auditoría)."""

    __tablename__ = "inventory_movements"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    delta: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
