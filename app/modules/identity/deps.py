"""Dependencias de autorización y de servicios del módulo de identidad."""

import uuid
from collections.abc import Awaitable, Callable

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.modules.identity.models import User, UserRole
from app.modules.identity.repository import UserRepository
from app.modules.identity.service import AuthService, UserService

bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_service(session: AsyncSession = Depends(get_session)) -> AuthService:
    """Provee el servicio de autenticación."""
    return AuthService(session)


def get_user_service(session: AsyncSession = Depends(get_session)) -> UserService:
    """Provee el servicio de perfil y direcciones."""
    return UserService(session)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resuelve el usuario autenticado a partir del access token JWT."""
    if credentials is None:
        raise AppError(401, "unauthorized", "Missing authentication credentials.")

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise AppError(401, "unauthorized", "Invalid or expired token.") from None

    if payload.get("type") != "access":
        raise AppError(401, "unauthorized", "Invalid or expired token.")

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise AppError(401, "unauthorized", "Invalid or expired token.")

    try:
        user_id = uuid.UUID(user_id_raw)
    except (TypeError, ValueError):
        raise AppError(401, "unauthorized", "Invalid or expired token.") from None

    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise AppError(401, "unauthorized", "Invalid or expired token.")
    return user


def require_roles(*roles: UserRole) -> Callable[..., Awaitable[User]]:
    """Devuelve una dependencia que exige uno de los roles indicados."""

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise AppError(403, "forbidden", "You do not have permission to perform this action.")
        return user

    return dependency
