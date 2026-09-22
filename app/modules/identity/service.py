"""Lógica de negocio del módulo de identidad."""

import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email_templates import (
    RESET_PASSWORD_PATH,
    VERIFY_EMAIL_PATH,
    EmailTemplate,
    frontend_link,
    humanize_minutes,
    render_email,
    resolve_language,
)
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
    RegisterOut,
    RegisterRequest,
    TokenPair,
    UserOut,
    UserUpdate,
)
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import NotificationService

logger = get_logger(__name__)

# Cada plantilla de correo tiene su tipo de notificación (el `type` que queda en la fila y que
# `EMAIL_ONLY_TYPES` mantiene fuera de la campana del frontend).
_TEMPLATE_NOTIFICATION_TYPES: dict[EmailTemplate, NotificationType] = {
    EmailTemplate.EMAIL_VERIFICATION: NotificationType.EMAIL_VERIFICATION,
    EmailTemplate.PASSWORD_RESET: NotificationType.PASSWORD_RESET,
}


def _utcnow() -> datetime:
    """Marca de tiempo UTC actual."""
    return datetime.now(UTC)


class AuthService:
    """Casos de uso de autenticación (registro, login, tokens, verificación)."""

    def __init__(self, session: AsyncSession, redis: Redis | None = None) -> None:
        self._session = session
        self._redis = redis
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)
        self._user_tokens = UserTokenRepository(session)

    async def register(self, data: RegisterRequest) -> RegisterOut:
        """Crea la cuenta **y deja la sesión iniciada** (devuelve el usuario y sus tokens).

        Enviar el correo de verificación no cambia: se encola igual y el usuario puede canjearlo
        cuando quiera. Que la verificación sea o no obligatoria lo decide `REQUIRE_VERIFIED_EMAIL`
        en los endpoints que publican o venden (decisión 0023), no el registro.
        """
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

        # El correo de confirmación va a la cola de notificaciones: se envía en segundo plano, así
        # que el registro responde sin esperar al servidor de correo.
        await self._queue_email(
            user=user,
            kind=EmailTemplate.EMAIL_VERIFICATION,
            path=VERIFY_EMAIL_PATH,
            token=token,
            expires_minutes=settings.EMAIL_VERIFICATION_EXPIRE_MINUTES,
        )

        # La sesión queda iniciada: mismos tokens que el login, en la misma transacción.
        pair, _ = await self._issue_token_pair(user)
        await self._session.commit()
        return RegisterOut(user=UserOut.model_validate(user), **pair.model_dump())

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
        await self._queue_email(
            user=user,
            kind=EmailTemplate.EMAIL_VERIFICATION,
            path=VERIFY_EMAIL_PATH,
            token=token,
            expires_minutes=settings.EMAIL_VERIFICATION_EXPIRE_MINUTES,
        )
        await self._session.commit()

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
            await self._queue_email(
                user=user,
                kind=EmailTemplate.PASSWORD_RESET,
                path=RESET_PASSWORD_PATH,
                token=token,
                expires_minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES,
            )
            await self._session.commit()

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

    async def _queue_email(
        self,
        *,
        user: User,
        kind: EmailTemplate,
        path: str,
        token: str,
        expires_minutes: int,
    ) -> None:
        """Deja el correo transaccional en la cola de notificaciones (**no** hace commit).

        El asunto y el cuerpo del correo son el `title` y el `body` de la notificación, así que el
        worker (`POST /admin/notifications/process`) los envía tal cual con el `EmailSender`
        configurado. El idioma sale del perfil del usuario y el enlace apunta al frontend, que es
        quien canjea el token contra la API.
        """
        if self._redis is None:
            # Sin Redis no hay cola (ocurre en pruebas unitarias que construyen el servicio a mano).
            logger.info("auth_email_not_queued", email=user.email, kind=kind.value)
            return

        profile = user.profile
        language = resolve_language(profile.preferred_language if profile else None)
        rendered = render_email(
            kind,
            language=language,
            full_name=(profile.full_name if profile else None) or user.email,
            site_name=settings.PROJECT_NAME,
            link=frontend_link(locale=language, path=path, token=token),
            expires=humanize_minutes(expires_minutes, language=language),
        )
        await NotificationService(self._session, self._redis).notify(
            user_id=user.id,
            type=_TEMPLATE_NOTIFICATION_TYPES[kind],
            title=rendered.subject,
            body=rendered.body,
            data={"template": kind.value},
            email_to=user.email,
        )

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
