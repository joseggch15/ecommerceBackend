"""Lógica de negocio del módulo de identidad."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.identity.models import (
    Address,
    RefreshToken,
    TokenType,
    User,
    UserProfile,
    UserRole,
    UserToken,
)
from app.modules.identity.repository import (
    AddressRepository,
    RefreshTokenRepository,
    UserRepository,
    UserTokenRepository,
)
from app.modules.identity.schemas import (
    AddressCreate,
    AddressUpdate,
    RegisterRequest,
    TokenPair,
    UserUpdate,
)

logger = get_logger(__name__)


def _utcnow() -> datetime:
    """Marca de tiempo UTC actual."""
    return datetime.now(UTC)


class AuthService:
    """Casos de uso de autenticación (registro, login, tokens, verificación)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)
        self._user_tokens = UserTokenRepository(session)

    async def register(self, data: RegisterRequest) -> User:
        existing = await self._users.get_by_email(data.email)
        if existing is not None:
            raise AppError(409, "email_already_registered", "This email is already registered.")

        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            role=UserRole.CUSTOMER,
        )
        user.profile = UserProfile(full_name=data.full_name)
        await self._users.add(user)

        token = generate_opaque_token()
        await self._user_tokens.add(
            UserToken(
                user_id=user.id,
                type=TokenType.EMAIL_VERIFICATION,
                token_hash=hash_token(token),
                expires_at=_utcnow()
                + timedelta(minutes=settings.EMAIL_VERIFICATION_EXPIRE_MINUTES),
            )
        )

        await self._session.commit()

        # Email simulado: el token se muestra en logs para pruebas manuales.
        # En la Fase 11 se enviará por email de verdad.
        logger.info("email_verification_token_generated", email=user.email, token=token)
        return user

    async def login(self, email: str, password: str) -> TokenPair:
        user = await self._users.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            raise AppError(401, "invalid_credentials", "Invalid email or password.")

        pair, _ = await self._issue_token_pair(user)
        await self._session.commit()
        return pair

    async def refresh(self, refresh_token: str) -> TokenPair:
        stored = await self._refresh_tokens.get_by_hash(hash_token(refresh_token))
        if stored is None or stored.revoked_at is not None or stored.expires_at <= _utcnow():
            raise AppError(401, "invalid_refresh_token", "Invalid or expired refresh token.")

        user = await self._users.get_by_id(stored.user_id)
        if user is None:
            raise AppError(401, "invalid_refresh_token", "Invalid or expired refresh token.")

        pair, new_record = await self._issue_token_pair(user)
        stored.revoked_at = _utcnow()
        stored.replaced_by = new_record.id
        await self._session.commit()
        return pair

    async def logout(self, refresh_token: str) -> None:
        stored = await self._refresh_tokens.get_by_hash(hash_token(refresh_token))
        if stored is not None and stored.revoked_at is None:
            stored.revoked_at = _utcnow()
            await self._session.commit()

    async def verify_email(self, token: str) -> None:
        stored = await self._user_tokens.get_by_hash(
            hash_token(token), TokenType.EMAIL_VERIFICATION
        )
        if stored is None or stored.used_at is not None or stored.expires_at <= _utcnow():
            raise AppError(400, "invalid_token", "Invalid or expired token.")

        user = await self._users.get_by_id(stored.user_id)
        if user is None:
            raise AppError(400, "invalid_token", "Invalid or expired token.")

        user.email_verified_at = _utcnow()
        stored.used_at = _utcnow()
        await self._session.commit()

    async def resend_verification(self, email: str) -> None:
        user = await self._users.get_by_email(email)
        if user is None or user.email_verified_at is not None:
            return  # No revelamos si el email existe o ya está verificado.

        token = generate_opaque_token()
        await self._user_tokens.add(
            UserToken(
                user_id=user.id,
                type=TokenType.EMAIL_VERIFICATION,
                token_hash=hash_token(token),
                expires_at=_utcnow()
                + timedelta(minutes=settings.EMAIL_VERIFICATION_EXPIRE_MINUTES),
            )
        )
        await self._session.commit()
        logger.info("email_verification_token_generated", email=user.email, token=token)

    async def request_password_reset(self, email: str) -> None:
        user = await self._users.get_by_email(email)
        if user is not None:
            token = generate_opaque_token()
            await self._user_tokens.add(
                UserToken(
                    user_id=user.id,
                    type=TokenType.PASSWORD_RESET,
                    token_hash=hash_token(token),
                    expires_at=_utcnow()
                    + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
                )
            )
            await self._session.commit()
            logger.info("password_reset_token_generated", email=user.email, token=token)

    async def reset_password(self, token: str, new_password: str) -> None:
        stored = await self._user_tokens.get_by_hash(hash_token(token), TokenType.PASSWORD_RESET)
        if stored is None or stored.used_at is not None or stored.expires_at <= _utcnow():
            raise AppError(400, "invalid_token", "Invalid or expired token.")

        user = await self._users.get_by_id(stored.user_id)
        if user is None:
            raise AppError(400, "invalid_token", "Invalid or expired token.")

        user.password_hash = hash_password(new_password)
        stored.used_at = _utcnow()
        # Por seguridad, al cambiar la contraseña se revocan todas las sesiones.
        await self._refresh_tokens.revoke_all_for_user(user.id)
        await self._session.commit()

    async def _issue_token_pair(self, user: User) -> tuple[TokenPair, RefreshToken]:
        access_token = create_access_token(str(user.id))
        raw_refresh = generate_opaque_token()
        record = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=_utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        self._session.add(record)
        await self._session.flush()
        return TokenPair(access_token=access_token, refresh_token=raw_refresh), record


class UserService:
    """Casos de uso del perfil y la libreta de direcciones."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._addresses = AddressRepository(session)

    async def update_profile(self, user: User, data: UserUpdate) -> User:
        profile = user.profile
        if profile is None:
            profile = UserProfile(user_id=user.id, full_name="")
            self._session.add(profile)
            user.profile = profile

        if data.full_name is not None:
            profile.full_name = data.full_name
        if data.preferred_currency is not None:
            profile.preferred_currency = data.preferred_currency
        if data.preferred_language is not None:
            profile.preferred_language = data.preferred_language
        if data.timezone is not None:
            profile.timezone = data.timezone

        await self._session.commit()
        return user

    async def list_addresses(self, user_id: uuid.UUID) -> list[Address]:
        return await self._addresses.list_by_user(user_id)

    async def create_address(self, user_id: uuid.UUID, data: AddressCreate) -> Address:
        existing = await self._addresses.list_by_user(user_id)
        is_default = True if not existing else data.is_default

        if is_default:
            await self._addresses.clear_default(user_id)

        address = Address(
            user_id=user_id,
            is_default=is_default,
            **data.model_dump(exclude={"is_default"}),
        )
        await self._addresses.add(address)
        await self._session.commit()
        return address

    async def update_address(
        self, user_id: uuid.UUID, address_id: uuid.UUID, data: AddressUpdate
    ) -> Address:
        address = await self._addresses.get_by_id_and_user(address_id, user_id)
        if address is None:
            raise AppError(404, "address_not_found", "Address not found.")

        values = data.model_dump(exclude_unset=True)
        values.pop("is_default", None)  # el "default" se maneja aparte

        for key, value in values.items():
            setattr(address, key, value)

        if data.is_default is True:
            await self._addresses.clear_default(user_id)
            address.is_default = True

        await self._session.commit()
        return address

    async def delete_address(self, user_id: uuid.UUID, address_id: uuid.UUID) -> None:
        address = await self._addresses.get_by_id_and_user(address_id, user_id)
        if address is None:
            raise AppError(404, "address_not_found", "Address not found.")
        address.deleted_at = _utcnow()
        await self._session.commit()
