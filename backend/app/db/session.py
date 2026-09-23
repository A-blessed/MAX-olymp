"""Подключение к базе и выдача сессий."""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config import get_settings
from .models import Base

# Импорт ради регистрации таблиц в метаданных Base: без него create_all
# не увидит модели каталога и не создаст их.
from ..catalog import models as _catalog_models  # noqa: F401
from ..personal import models as _personal_models  # noqa: F401

logger = logging.getLogger(__name__)

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,  # переподключается, если Postgres перезапустили
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI: сессия на время запроса."""
    async with get_session_factory()() as session:
        yield session


async def init_models() -> None:
    """Создаёт таблицы, которых ещё нет.

    Для MVP этого достаточно. Для продакшена сюда встанет Alembic:
    ``create_all`` не умеет изменять уже существующие таблицы.
    """
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    logger.info("Схема базы данных синхронизирована")


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
