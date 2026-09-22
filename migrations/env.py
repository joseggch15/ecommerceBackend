"""Configuración de Alembic para migraciones asíncronas (PostgreSQL/asyncpg)."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.modules.cart.models
import app.modules.catalog.models
import app.modules.identity.models
import app.modules.inventory.models
import app.modules.notifications.models
import app.modules.orders.models
import app.modules.payments.models
import app.modules.promotions.models
import app.modules.reviews.models
import app.modules.sellers.models
import app.modules.shipping.models
from app.core.config import settings
from app.core.database import Base

# Los imports de arriba existen por su efecto secundario: registran las tablas en
# `Base.metadata`. Si se pierden, `alembic revision --autogenerate` genera una
# migración que DROPEA todas las tablas. Esta lista los mantiene "usados" y, de
# paso, comprobamos que el metadata quedó completo antes de migrar nada.
_MODEL_MODULES = (
    app.modules.cart.models,
    app.modules.catalog.models,
    app.modules.identity.models,
    app.modules.inventory.models,
    app.modules.notifications.models,
    app.modules.orders.models,
    app.modules.payments.models,
    app.modules.promotions.models,
    app.modules.reviews.models,
    app.modules.sellers.models,
    app.modules.shipping.models,
)

_REQUIRED_TABLES = {"users", "stores", "products", "carts", "orders", "payments", "shipments"}
_missing_tables = _REQUIRED_TABLES - set(Base.metadata.tables)
if _missing_tables:
    raise RuntimeError(f"Modelos sin importar en migrations/env.py: {sorted(_missing_tables)}")

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
