"""Schemas Pydantic del módulo de identidad (entrada/salida de la API)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.identity.models import UserRole


def _normalize_email(value: str) -> str:
    """Normaliza un email (minúsculas y sin espacios)."""
    return value.strip().lower()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class EmailRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class VerifyEmailRequest(BaseModel):
    token: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


# ---------- Perfil ----------


class UserProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    full_name: str
    preferred_currency: str
    preferred_language: str
    timezone: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: UserRole
    email_verified: bool
    created_at: datetime
    profile: UserProfileOut | None = None


class RegisterOut(BaseModel):
    """Respuesta del registro: la cuenta creada **y** su par de tokens.

    El registro deja la sesión iniciada (decisión 0023), así que devuelve los mismos tokens que el
    login **más** el usuario: el cliente que empieza a usarlos (el BFF del frontend) necesita su
    perfil para construir la sesión y así se ahorra una petición extra a `GET /users/me`.
    """

    user: UserOut
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserUpdate(BaseModel):

    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    preferred_currency: str | None = Field(default=None, min_length=3, max_length=3)
    preferred_language: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("preferred_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value


# ---------- Direcciones ----------


class AddressCreate(BaseModel):
    label: str = Field(min_length=1, max_length=50)
    recipient_name: str = Field(min_length=1, max_length=120)
    line1: str = Field(min_length=1, max_length=255)
    line2: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=1, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str = Field(min_length=2, max_length=2)
    phone: str | None = Field(default=None, max_length=30)
    is_default: bool = False

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.upper()


class AddressUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=50)
    recipient_name: str | None = Field(default=None, min_length=1, max_length=120)
    line1: str | None = Field(default=None, min_length=1, max_length=255)
    line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    phone: str | None = Field(default=None, max_length=30)
    is_default: bool | None = None

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class AddressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    recipient_name: str
    line1: str
    line2: str | None
    city: str
    state: str | None
    postal_code: str | None
    country: str
    phone: str | None
    is_default: bool
