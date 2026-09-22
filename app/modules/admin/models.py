"""Modelos ORM del módulo de administración.

`admin_actions` es el **libro de auditoría**: cada acción de moderación o de
administración queda registrada con quién la hizo, sobre qué y por qué.
"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.base import TimestampMixin, UUIDPrimaryKeyMixin


class AdminAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Acción administrativa (auditoría)."""

    __tablename__ = "admin_actions"

    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
