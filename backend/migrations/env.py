"""Окружение Alembic.

Адрес базы берётся из настроек приложения, а не из alembic.ini: так он
задаётся единственной переменной DATABASE_URL и не расходится с тем, с
чем работает сам сервис.

Драйвер asyncpg асинхронный, поэтому миграции выполняются через
async-движок с синхронным колбэком внутри соединения.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db.models import Base

# Импорт ради регистрации таблиц в метаданных: без него autogenerate
# решит, что таблиц каталога и пользовательской части не существует,
# и предложит их удалить.
from app.catalog import models as _catalog_models  # noqa: F401
from app.personal import models as _personal_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Генерация SQL без подключения к базе: `alembic upgrade --sql`."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Без этого изменение типа колонки не попадёт в autogenerate.
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(get_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
