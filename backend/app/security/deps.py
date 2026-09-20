"""Зависимости FastAPI для аутентификации мини-приложения.

Договорённость с фронтендом: строка запуска передаётся заголовком

    Authorization: tma <initData>

где ``<initData>`` — значение ``window.WebApp.initData``, декодированное
ровно один раз. Схема ``tma`` выбрана по аналогии с другими платформами
мини-приложений; главное — не менять её потом на ходу.

Проверка выполняется на каждом запросе: строка подписана один раз при
запуске, отдельная сессия не заводится. Защита от бесконечного
переиспользования перехваченной строки — проверка ``auth_date``.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db.models import User, utcnow
from ..db.session import get_session
from ..max_api.client import MaxApiClient
from . import launch_data as launch

logger = logging.getLogger(__name__)

AUTH_SCHEME = "tma"


def get_max_client(request: Request) -> MaxApiClient:
    """Общий клиент Bot API, созданный при старте приложения."""
    client: Optional[MaxApiClient] = getattr(request.app.state, "max_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Клиент MAX API не инициализирован: не задан BOT_TOKEN",
        )
    return client


def _extract_raw_launch_data(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нет заголовка Authorization с данными запуска",
            headers={"WWW-Authenticate": AUTH_SCHEME},
        )

    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != AUTH_SCHEME or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Ожидается заголовок вида 'Authorization: {AUTH_SCHEME} <initData>'",
            headers={"WWW-Authenticate": AUTH_SCHEME},
        )
    return value.strip()


async def get_launch_data(
    authorization: Optional[str] = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> launch.LaunchData:
    """Проверяет подпись данных запуска и возвращает доверенные данные."""
    # Пустой токен — это поломка конфигурации сервера, а не проблема клиента.
    # Без этой ветки наружу ушло бы 401 "данные не прошли проверку", и
    # отладка свелась бы к поиску несуществующей ошибки подписи.
    if not settings.bot_token:
        logger.error("BOT_TOKEN не задан — проверить подпись данных запуска невозможно")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "bot_token_missing", "message": "Сервер не настроен"},
        )

    raw = _extract_raw_launch_data(authorization)

    try:
        return launch.validate(
            raw,
            bot_token=settings.bot_token,
            ttl_seconds=settings.launch_data_ttl_or_none,
        )
    except launch.LaunchDataExpired as exc:
        # Отдельный код, чтобы фронтенд мог переоткрыть мини-приложение
        # и получить свежую подписанную строку вместо показа ошибки.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": exc.code, "message": str(exc)},
            headers={"WWW-Authenticate": AUTH_SCHEME},
        ) from exc
    except launch.LaunchDataError as exc:
        # Подробности пишем в лог, наружу отдаём только код ошибки:
        # по тексту не должно быть видно, что именно не сошлось.
        logger.warning("Отклонены данные запуска (%s): %s", exc.code, exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": exc.code, "message": "Данные запуска не прошли проверку"},
            headers={"WWW-Authenticate": AUTH_SCHEME},
        ) from exc


async def get_current_user(
    data: launch.LaunchData = Depends(get_launch_data),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Возвращает пользователя из БД, создавая запись при первом заходе."""
    profile = data.user

    values = {
        "id": profile.id,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "username": profile.username,
        "language_code": profile.language_code,
        "photo_url": profile.photo_url,
        "last_seen_at": utcnow(),
    }
    # start_param приходит только при запуске по диплинку — не затираем
    # сохранённое значение пустым при обычных заходах.
    if data.start_param:
        values["start_param"] = data.start_param

    statement = (
        pg_insert(User)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[User.id],
            set_={key: value for key, value in values.items() if key != "id"},
        )
        .returning(User)
    )

    result = await session.execute(statement)
    await session.commit()
    return result.scalar_one()
