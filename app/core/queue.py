"""Cola de trabajos en Redis para tareas en segundo plano.

Es deliberadamente simple (lista FIFO): el monolito encola y un proceso aparte
—o el endpoint de administración `POST /admin/notifications/process` en
desarrollo— los consume. Migrar a Celery/RQ/Arq no cambia el resto del dominio.
"""

import json
from typing import Any

from redis.asyncio import Redis

QUEUE_KEY = "jobs:notifications"


async def enqueue(redis: Redis, job: dict[str, Any]) -> int:
    """Encola un trabajo y devuelve el tamaño actual de la cola."""
    length = await redis.rpush(QUEUE_KEY, json.dumps(job))
    return int(length)


async def dequeue_batch(redis: Redis, *, limit: int) -> list[dict[str, Any]]:
    """Saca hasta `limit` trabajos de la cola (FIFO)."""
    jobs: list[dict[str, Any]] = []
    for _ in range(limit):
        raw = await redis.lpop(QUEUE_KEY)
        if raw is None:
            break
        if isinstance(raw, bytes):
            text = raw.decode()
        elif isinstance(raw, str):
            text = raw
        else:
            continue
        jobs.append(json.loads(text))
    return jobs


async def requeue(redis: Redis, job: dict[str, Any]) -> None:
    """Devuelve un trabajo a la cola (reintento)."""
    await redis.rpush(QUEUE_KEY, json.dumps(job))


async def queue_size(redis: Redis) -> int:
    return int(await redis.llen(QUEUE_KEY))
