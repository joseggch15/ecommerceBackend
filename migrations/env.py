"""Configuración de Alembic para migraciones asíncronas (PostgreSQL/asyncpg)."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importa los modelos de negocio para que Alembic los detecte (autogenerate).
import app.modules.cart.models
import app.modules.catalog.models
import app.modules.identity.models
import app.modules.inventory.models
import app.modules.orders.models
import app.modules.payments.models
import app.modules.sellers.models  # noqa: F401
from app.core.config import settings
from app.core.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Los modelos se importan aquí para que Alembic los detecte (autogenerate).
# En la Fase 0 todavía no hay modelos de negocio.
target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """Ejecuta las migraciones en modo offline (genera SQL sin conectarse)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Ejecuta las migraciones sobre una conexión ya establecida."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Crea un motor asíncrono y ejecuta las migraciones en línea."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Punto de entrada para migraciones en línea (con conexión real)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
