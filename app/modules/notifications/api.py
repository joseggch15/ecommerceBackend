"""Endpoints del módulo de notificaciones (in-app, emails y cola)."""

import uuid

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.redis import get_redis
from app.modules.identity.deps import get_current_user, require_roles
from app.modules.identity.models import User, UserRole
from app.modules.notifications.schemas import (
    EmailOut,
    JobRunOut,
    NotificationListOut,
    NotificationOut,
)
from app.modules.notifications.service import NotificationService

router = APIRouter(tags=["notifications"])


def get_notification_service(
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> NotificationService:
    return NotificationService(session, redis)


@router.get("/notifications", response_model=NotificationListOut)
async def list_notifications(
    only_unread: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationListOut:
    """Mis notificaciones (incluye cuántas sin leer)."""
    return await service.list_for_user(user.id, only_unread=only_unread, limit=limit)


# OJO: va antes de /notifications/{notification_id}/read para que "read-all" no
# se interprete como un UUID.
@router.post("/notifications/read-all", response_model=NotificationListOut)
async def mark_all_read(
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationListOut:
    """Marca como leídas todas mis notificaciones."""
    return await service.mark_all_read(user.id)


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationOut:
    """Marca como leída una notificación propia."""
    return await service.mark_read(user.id, notification_id)


@router.get("/admin/notifications/emails", response_model=list[EmailOut])
async def list_emails(
    limit: int = Query(default=50, ge=1, le=200),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: NotificationService = Depends(get_notification_service),
) -> list[EmailOut]:
    """Emails generados y su estado de envío (solo admin)."""
    return await service.list_emails(limit=limit)


@router.post("/admin/notifications/process", response_model=JobRunOut)
async def process_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: NotificationService = Depends(get_notification_service),
) -> JobRunOut:
    """Procesa la cola de emails.

    En desarrollo hace de worker (en producción corre en un proceso aparte).
    """
    return await service.process_pending(limit=limit)
