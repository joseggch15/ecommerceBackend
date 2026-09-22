"""Modelos ORM del módulo de identidad."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base import (
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_values,
)


class UserRole(enum.StrEnum):
    """Rol de acceso a la plataforma."""

    CUSTOMER = "customer"
    ADMIN = "admin"


class TokenType(enum.StrEnum):
    """Tipo de token de un solo uso."""

    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Cuenta de usuario: identidad y autenticación."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=False, values_callable=enum_values),
        nullable=False,
        default=UserRole.CUSTOMER,
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", uselist=False, lazy="selectin"
    )
    addresses: Mapped[list["Address"]] = relationship(back_populates="user")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user")
    user_tokens: Mapped[list["UserToken"]] = relationship(back_populates="user")

    @property
    def email_verified(self) -> bool:
        """Indica si el usuario verificó su email."""
        return self.email_verified_at is not None


class UserProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Perfil del usuario (datos y preferencias, relación 1:1 con users)."""

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    preferred_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="COP")
    preferred_language: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Bogota")

    user: Mapped[User] = relationship(back_populates="profile")


class Address(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Dirección de envío del usuario (libreta de direcciones)."""

    __tablename__ = "addresses"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(120), nullable=False)
    line1: Mapped[str] = mapped_column(String(255), nullable=False)
    line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)  # ISO 3166-1 alpha-2
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="addresses")


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    """Refresh token persistido (hash) para rotación y revocación."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class UserToken(UUIDPrimaryKeyMixin, Base):
    """Token de un solo uso (verificación de email / recuperación de contraseña)."""

    __tablename__ = "user_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    type: Mapped[TokenType] = mapped_column(
        Enum(TokenType, name="user_token_type", native_enum=False, values_callable=enum_values),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="user_tokens")
