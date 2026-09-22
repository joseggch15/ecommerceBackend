"""Repositorios del módulo de administración.

De momento solo el **directorio de usuarios** del panel (F9): el listado paginado con búsqueda
por correo y filtro por rol. No hay migración: todo sale de tablas que ya existen (`users`,
`user_profiles` y `stores`), con dos *outer joins* para no dejar fuera a quien no tiene perfil o
tienda. Nunca se selecciona `password_hash` ni `token_hash`: no es que se filtren después, es que
**no se leen de la base de datos** (así no hay forma de exponerlos por descuido).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import User, UserProfile, UserRole
from app.modules.sellers.models import Store, StoreStatus


@dataclass(frozen=True)
class AdminUserRow:
    """Fila del listado de usuarios, ya unida con su perfil y su tienda."""

    id: uuid.UUID
    email: str
    role: UserRole
    email_verified: bool
    full_name: str | None
    store_id: uuid.UUID | None
    store_name: str | None
    store_status: StoreStatus | None
    created_at: datetime


class AdminUserRepository:
    """Listado de usuarios de la plataforma (respeta el borrado lógico)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_users(
        self,
        *,
        q: str | None,
        role: UserRole | None,
        limit: int,
        cursor: tuple[datetime, uuid.UUID] | None,
    ) -> list[AdminUserRow]:
        """Usuarios del más reciente al más antiguo, con búsqueda por correo y filtro por rol.

        El orden es `created_at DESC, id DESC` para que el cursor sea **estable**: si dos cuentas
        se crean en el mismo instante, el id desempata y ninguna fila se repite ni se pierde entre
        páginas (mismo patrón que las reseñas y las preguntas).
        """
        stmt = (
            select(
                User.id,
                User.email,
                User.role,
                User.email_verified_at,
                User.created_at,
                UserProfile.full_name,
                Store.id,
                Store.name,
                Store.status,
            )
            .select_from(User)
            .outerjoin(UserProfile, UserProfile.user_id == User.id)
            .outerjoin(Store, and_(Store.user_id == User.id, Store.deleted_at.is_(None)))
            .where(User.deleted_at.is_(None))
            .order_by(User.created_at.desc(), User.id.desc())
            .limit(limit)
        )
        if q:
            stmt = stmt.where(User.email.ilike(f"%{q}%"))
        if role is not None:
            stmt = stmt.where(User.role == role)
        if cursor is not None:
            created_at, user_id = cursor
            stmt = stmt.where(
                or_(
                    User.created_at < created_at,
                    (User.created_at == created_at) & (User.id < user_id),
                )
            )

        result = await self._session.execute(stmt)
        return [
            AdminUserRow(
                id=row[0],
                email=row[1],
                role=row[2],
                email_verified=row[3] is not None,
                full_name=row[5],
                store_id=row[6],
                store_name=row[7],
                store_status=row[8],
                created_at=row[4],
            )
            for row in result.all()
        ]
