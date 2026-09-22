"""Rate limiting simple con Redis (ventana fija por IP)."""

from collections.abc import Awaitable, Callable

from fastapi import Depends, Request
from redis.asyncio import Redis

from app.core.errors import AppError
from app.core.redis import get_redis


def rate_limit(scope: str, limit: int, window_seconds: int) -> Callable[..., Awaitable[None]]:
    """Devuelve una dependencia de FastAPI que limita peticiones por IP."""

    async def dependency(
        request: Request,
        redis: Redis = Depends(get_redis),
    ) -> None:
        client_ip = request.client.host if request.client else "unknown"
        key = f"rate_limit:{scope}:{client_ip}"

        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
        if count > limit:
            raise AppError(
                status_code=429,
                code="too_many_requests",
                detail="Too many requests. Please try again later.",
            )

    return dependency
