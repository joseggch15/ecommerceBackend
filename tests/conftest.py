"""Fixtures compartidas de pytest."""

import asyncio
from collections.abc import AsyncIterator, Iterator

import asyncpg  # type: ignore[import-untyped]  # asyncpg no distribuye stubs de tipos
import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base, get_session
from app.core.redis import get_redis
from app.main import app

# Base de datos y Redis dedicados a las pruebas (corren en Docker).
TEST_DATABASE_URL = "postgresql+asyncpg://marketplace:marketplace@localhost:5433/marketplace_test"
TEST_REDIS_URL = "redis://localhost:6379/1"


async def _create_test_database() -> None:
    """Crea la base de datos de pruebas si no existe (loop propio)."""
    conn = await asyncpg.connect(
        user="marketplace",
        password="marketplace",
        host="localhost",
        port=5433,
        database="postgres",
    )
    exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'marketplace_test'")
    if not exists:
        await conn.execute("CREATE DATABASE marketplace_test")
    await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_database() -> None:
    """Crea la base de datos de pruebas una sola vez por sesión."""
    asyncio.run(_create_test_database())


@pytest.fixture(autouse=True)
def _clear_dependency_overrides() -> Iterator[None]:
    """Limpia los dependency_overrides después de cada prueba."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Cliente HTTP liviano (sin base de datos); para pruebas con dependencias mockeadas."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Motor asíncrono contra la base de datos de pruebas (tablas creadas/limpiadas)."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Sesión directa a la base de pruebas (para preparar datos en los tests)."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def integration_client(db_engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    """Cliente HTTP con la app conectada a la BD y Redis de pruebas."""
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    test_redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await test_redis.flushdb()

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_redis] = lambda: test_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await test_redis.aclose()
