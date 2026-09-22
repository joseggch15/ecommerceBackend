"""Pruebas del worker de la cola de correos (dentro del proceso de la API)."""

import asyncio

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.email import CapturingEmailSender
from app.modules.identity.models import User, UserProfile, UserRole
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import NotificationService
from app.modules.notifications.worker import process_notifications_once, run_notification_worker

TEST_REDIS_URL = "redis://localhost:6379/1"


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def test_process_notifications_once_sends_what_was_queued(
    db_engine: AsyncEngine, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una pasada del worker vacía la cola y envía los correos pendientes."""
    monkeypatch.setattr(settings, "EMAIL_SENDER", "capturing")
    CapturingEmailSender.reset()

    redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await redis.flushdb()
    try:
        user = User(email="worker@example.com", password_hash="no-se-usa", role=UserRole.CUSTOMER)
        user.profile = UserProfile(full_name="Worker")
        db_session.add(user)
        await db_session.flush()
        await NotificationService(db_session, redis).notify(
            user_id=user.id,
            type=NotificationType.EMAIL_VERIFICATION,
            title="Asunto de prueba",
            body="Cuerpo de prueba",
            email_to="worker@example.com",
        )
        await db_session.commit()

        pending = await process_notifications_once(redis, _factory(db_engine))

        assert pending == 0
        assert [email.to for email in CapturingEmailSender.sent] == ["worker@example.com"]
        assert CapturingEmailSender.sent[0].subject == "Asunto de prueba"
    finally:
        await redis.aclose()


async def test_worker_loop_stops_with_the_stop_event(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El bucle termina cuando el arranque le pide parar (no se queda colgado al apagar)."""
    monkeypatch.setattr(settings, "EMAIL_SENDER", "capturing")

    redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await redis.flushdb()
    try:
        stop = asyncio.Event()
        task = asyncio.create_task(
            run_notification_worker(
                redis=redis,
                session_factory=_factory(db_engine),
                interval_seconds=0.01,
                stop=stop,
            )
        )
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=5)
    finally:
        await redis.aclose()
