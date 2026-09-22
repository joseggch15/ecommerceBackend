"""Lógica de negocio del módulo de notificaciones.

`notify()` crea el aviso **in-app** y, si hay destinatario, deja el email en
estado `queued` y lo encola en Redis. `process_pending()` consume la cola y
"envía" con el `EmailSender` configurado (en desarrollo escribe en el log),
marcando `sent`/`failed` y **reencolando** los fallos para reintentar.
"""

import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import get_email_sender
from app.core.errors import AppError
from app.core.queue import dequeue_batch, enqueue, queue_size, requeue
from app.modules.notifications.models import EmailStatus, Notification, NotificationType
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import (
    EmailOut,
    JobRunOut,
    NotificationListOut,
    NotificationOut,
)

MAX_ATTEMPTS = 3


def _notification_out(notification: Notification) -> NotificationOut:
    return NotificationOut(
        id=notification.id,
        type=notification.type.value,
        title=notification.title,
        body=notification.body,
        data=notification.data,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


class NotificationService:
    """Avisos in-app, emails en cola y proceso de la cola."""

    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self._session = session
        self._redis = redis
        self._notifications = NotificationRepository(session)

    async def notify(
        self,
        *,
        user_id: uuid.UUID,
        type: NotificationType,
        title: str,
        body: str,
        data: dict[str, object] | None = None,
        email_to: str | None = None,
    ) -> Notification:
        """Crea el aviso in-app y encola el email si hay destinatario.

        **No** hace commit: se usa dentro de transacciones de otros módulos
        (p. ej. al confirmarse un pago), que son las que confirman.
        """
        notification = await self._notifications.add(
            Notification(
                user_id=user_id,
                type=type,
                title=title,
                body=body,
                data=data or {},
                email_to=email_to,
                email_status=EmailStatus.QUEUED if email_to else None,
            )
        )
        if email_to:
            await enqueue(self._redis, {"notification_id": str(notification.id), "attempt": 1})
        return notification

    async def list_for_user(
        self, user_id: uuid.UUID, *, only_unread: bool = False, limit: int = 20
    ) -> NotificationListOut:
        """Notificaciones del usuario (más recientes primero) y cuántas sin leer."""
        items = await self._notifications.list_for_user(
            user_id, only_unread=only_unread, limit=limit
        )
        return NotificationListOut(
            items=[_notification_out(item) for item in items],
            unread_count=await self._notifications.count_unread(user_id),
        )

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> NotificationOut:
        """Marca como leída una notificación propia."""
        notification = await self._notifications.get_by_id(notification_id)
        if notification is None or notification.user_id != user_id:
            raise AppError(404, "notification_not_found", "Notification not found.")
        if notification.read_at is None:
            notification.read_at = datetime.now(UTC)
            await self._session.commit()
        return _notification_out(notification)

    async def mark_all_read(self, user_id: uuid.UUID) -> NotificationListOut:
        """Marca como leídas todas las notificaciones del usuario."""
        await self._notifications.mark_all_read(user_id)
        await self._session.commit()
        return await self.list_for_user(user_id, only_unread=False, limit=50)

    async def list_emails(self, *, limit: int = 50) -> list[EmailOut]:
        """Emails generados (vista de administración)."""
        rows = await self._notifications.list_emails(limit)
        return [
            EmailOut(
                id=row.id,
                user_id=row.user_id,
                type=row.type.value,
                email_to=row.email_to,
                email_status=row.email_status.value if row.email_status else None,
                email_error=row.email_error,
                sent_at=row.sent_at,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def process_pending(self, *, limit: int = 20) -> JobRunOut:
        """Consume la cola y envía los emails pendientes (con reintentos)."""
        sender = get_email_sender()
        jobs = await dequeue_batch(self._redis, limit=limit)
        sent = 0
        failed = 0

        for job in jobs:
            notification = await self._load_job_notification(job)
            if notification is None or notification.email_to is None:
                failed += 1
                continue

            attempt = int(str(job.get("attempt", 1)))
            try:
                await sender.send(
                    to=notification.email_to,
                    subject=notification.title,
                    body=notification.body,
                )
            except Exception as exc:
                notification.email_status = EmailStatus.FAILED
                notification.email_error = str(exc)
                failed += 1
                if attempt < MAX_ATTEMPTS:
                    await requeue(
                        self._redis,
                        {"notification_id": str(notification.id), "attempt": attempt + 1},
                    )
            else:
                notification.email_status = EmailStatus.SENT
                notification.email_error = None
                notification.sent_at = datetime.now(UTC)
                sent += 1

        await self._session.commit()
        return JobRunOut(
            processed=len(jobs),
            sent=sent,
            failed=failed,
            pending=await queue_size(self._redis),
        )

    async def _load_job_notification(self, job: dict[str, object]) -> Notification | None:
        raw_id = job.get("notification_id")
        if not raw_id:
            return None
        try:
            notification_id = uuid.UUID(str(raw_id))
        except ValueError:
            return None
        return await self._notifications.get_by_id(notification_id)
