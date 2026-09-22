"""Cliente Redis asíncrono compartido."""

from redis.asyncio import Redis

from app.core.config import settings

redis_client: Redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)


def get_redis() -> Redis:
    """Dependencia de FastAPI: provee el cliente Redis compartido."""
    return redis_client
