"""Repositorios del módulo de notificaciones."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification


class NotificationRepository:
    """Acceso a notificaciones (in-app y emails)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, notification: Notification) -> Notification:
        self._session.add(notification)
        await self._session.flush()
        return notification

    async def get_by_id(self, notification_id: uuid.UUID) -> Notification | None:
        result = await self._session.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, only_unread: bool, limit: int
    ) -> list[Notification]:
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        if only_unread:
            stmt = stmt.where(Notification.read_at.is_(None))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_unread(self, user_id: uuid.UUID) -> int:
        count = await self._session.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id, Notification.read_at.is_(None)
            )
        )
        return int(count or 0)

    async def mark_all_read(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=func.now())
        )

    async def list_emails(self, limit: int) -> list[Notification]:
        result = await self._session.execute(
            select(Notification)
            .where(Notification.email_to.is_not(None))
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
