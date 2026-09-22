"""Schemas Pydantic del módulo de notificaciones."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    body: str
    data: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    unread_count: int


class EmailOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    email_to: str | None
    email_status: str | None
    email_error: str | None
    sent_at: datetime | None
    created_at: datetime


class JobRunOut(BaseModel):
    """Resultado de procesar la cola de trabajos."""

    processed: int
    sent: int
    failed: int
    pending: int
