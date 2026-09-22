"""Pruebas unitarias del rate limiting (ventana fija)."""

import pytest

from app.core.errors import AppError
from app.core.rate_limit import rate_limit


class FakeRedis:
    """Redis en memoria para probar el contador de la ventana fija."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True


class FakeRequest:
    """Request mínimo con IP de cliente."""

    class _Client:
        host = "127.0.0.1"

    client = _Client()


async def test_rate_limit_allows_up_to_limit() -> None:
    redis = FakeRedis()
    dependency = rate_limit("test", limit=3, window_seconds=60)

    for _ in range(3):
        await dependency(FakeRequest(), redis)  # no debe lanzar


async def test_rate_limit_rejects_above_limit() -> None:
    redis = FakeRedis()
    dependency = rate_limit("test", limit=3, window_seconds=60)

    for _ in range(3):
        await dependency(FakeRequest(), redis)

    with pytest.raises(AppError) as exc_info:
        await dependency(FakeRequest(), redis)

    assert exc_info.value.code == "too_many_requests"
