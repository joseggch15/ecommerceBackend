"""Modelos ORM del módulo de notificaciones.

Una notificación es, a la vez, el aviso **in-app** del usuario y (si se indica
un destinatario) el **email** que se encola para enviarse en segundo plano.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.base import TimestampMixin, UUIDPrimaryKeyMixin, enum_values


class NotificationType(enum.StrEnum):
    """Motivo de la notificación (el frontend decide el icono/destino)."""

    ORDER_PAID = "order_paid"
    ORDER_SHIPPED = "order_shipped"
    ORDER_DELIVERED = "order_delivered"
    ORDER_CANCELLED = "order_cancelled"
    WELCOME = "welcome"


class EmailStatus(enum.StrEnum):
    """Estado del envío del email asociado."""

    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Aviso para un usuario (in-app y, opcionalmente, por email)."""

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(
            NotificationType,
            name="notification_type",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Email opcional (se envía en segundo plano desde la cola).
    email_to: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_status: Mapped[EmailStatus | None] = mapped_column(
        Enum(EmailStatus, name="email_status", native_enum=False, values_callable=enum_values),
        nullable=True,
    )
    email_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
