"""Worker de la cola de correos.

En producción el worker es un **proceso aparte** (decisión 0015: `while True: process_pending()`).
Para que la demo funcione sin levantar nada más, el monolito puede arrancar este mismo bucle dentro
de su proceso cuando `NOTIFICATION_WORKER_ENABLED=true` (así está el `.env` de desarrollo): cada
pocos segundos vacía la cola y envía lo que haya. Con el valor por defecto (`false`), el envío se
dispara a mano con `POST /admin/notifications/process`.
"""

import asyncio

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.core.queue import queue_size
from app.modules.notifications.service import NotificationService

logger = get_logger(__name__)


async def process_notifications_once(
    redis: Redis, session_factory: async_sessionmaker[AsyncSession], *, limit: int = 50
) -> int:
    """Vacía la cola una vez y devuelve cuántos trabajos quedan pendientes.

    Cada trabajo se envía con su propia transacción (`process_pending` hace `commit`), así que un
    fallo del servidor de correo no arrastra a los demás.
    """
    async with session_factory() as session:
        result = await NotificationService(session, redis).process_pending(limit=limit)
    if result.processed:
        logger.info(
            "notification_worker_run",
            processed=result.processed,
            sent=result.sent,
            failed=result.failed,
        )
    return await queue_size(redis)


async def run_notification_worker(
    *,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    interval_seconds: float,
    stop: asyncio.Event | None = None,
) -> None:
    """Bucle del worker: vacía la cola y espera `interval_seconds` entre pasadas.

    Se le pasa el `stop` (un `asyncio.Event`) para que el arranque de la aplicación pueda pararlo
    limpiamente al apagarse. Un error inesperado **no** tumba el bucle: se registra y se sigue.
    """
    while stop is None or not stop.is_set():
        try:
            await process_notifications_once(redis, session_factory)
        except Exception as exc:  # el worker nunca puede tumbar la API
            logger.warning("notification_worker_error", error=str(exc))
        await asyncio.sleep(interval_seconds)
