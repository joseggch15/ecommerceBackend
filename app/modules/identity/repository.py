"""Repositorios del módulo de identidad (acceso a datos)."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import Address, RefreshToken, TokenType, User, UserToken


class UserRepository:
    """Acceso a la tabla de usuarios (respeta el borrado lógico)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email == email, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._session.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def add(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user


class AddressRepository:
    """Acceso a la libreta de direcciones (respeta el borrado lógico)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_user(self, user_id: uuid.UUID) -> list[Address]:
        result = await self._session.execute(
            select(Address)
            .where(Address.user_id == user_id, Address.deleted_at.is_(None))
            .order_by(Address.created_at)
        )
        return list(result.scalars().all())

    async def get_by_id_and_user(self, address_id: uuid.UUID, user_id: uuid.UUID) -> Address | None:
        result = await self._session.execute(
            select(Address).where(
                Address.id == address_id,
                Address.user_id == user_id,
                Address.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def add(self, address: Address) -> Address:
        self._session.add(address)
        await self._session.flush()
        return address

    async def clear_default(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            update(Address)
            .where(Address.user_id == user_id, Address.deleted_at.is_(None))
            .values(is_default=False)
        )


class RefreshTokenRepository:
    """Acceso a los refresh tokens persistidos."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )


class UserTokenRepository:
    """Acceso a los tokens de un solo uso (verificación / recuperación)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hash(self, token_hash: str, token_type: TokenType) -> UserToken | None:
        result = await self._session.execute(
            select(UserToken).where(
                UserToken.token_hash == token_hash, UserToken.type == token_type
            )
        )
        return result.scalar_one_or_none()

    async def add(self, token: UserToken) -> UserToken:
        self._session.add(token)
        await self._session.flush()
        return token
