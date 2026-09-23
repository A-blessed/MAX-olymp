"""Точка входа бэкенда.

Один сервис обслуживает два контура сразу:

* ``/webhook`` — события бота, авторизация по секрету в заголовке;
* ``/api/*``   — мини-приложение, авторизация по подписи данных запуска.

Контуры разные и не должны путаться, но живут в одном процессе
сознательно: вебхук обязан быть доступен по HTTPS на порту 443, и держать
ради этого два публичных адреса с двумя сертификатами незачем. Один
домен — один туннель — один сертификат.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.catalog import router as catalog_router
from .api.personal import router as personal_router
from .api.router import router as api_router
from .bot.router import router as bot_router
from .config import get_settings
from .db.session import dispose_engine
from .max_api.client import MaxApiClient

logger = logging.getLogger(__name__)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)

    logger.info("Запуск в режиме %s", settings.app_env)

    if settings.bot_token:
        ca_files = settings.extra_ca_files()
        if not ca_files:
            logger.warning(
                "В каталоге %s нет сертификатов. Обращения к %s, скорее всего, "
                "упадут с ошибкой TLS: домен подписан сертификатом Минцифры.",
                settings.extra_ca_certs_dir,
                settings.max_api_base_url,
            )
        app.state.max_client = MaxApiClient(
            token=settings.bot_token,
            base_url=settings.max_api_base_url,
            timeout=settings.max_api_timeout,
            extra_ca_files=ca_files,
        )
    else:
        # Приложение поднимается и без токена: так можно гонять тесты и
        # смотреть /docs, не имея на руках рабочего бота.
        app.state.max_client = None
        logger.warning("BOT_TOKEN не задан — вызовы MAX API недоступны")

    try:
        yield
    finally:
        if app.state.max_client is not None:
            await app.state.max_client.aclose()
        await dispose_engine()
        logger.info("Остановлено")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="MAX mini app backend",
        version="0.1.0",
        lifespan=lifespan,
        # В проде схему API наружу не отдаём.
        docs_url=None if settings.is_production else "/docs",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # Мини-приложение открывается с другого origin, поэтому CORS нужен.
    #
    # Заголовки разрешаем любые. Жёсткий список тут не защита — доступ
    # ограничивают origin и подпись данных запуска, — зато он ломается,
    # как только между фронтендом и сервером появляется прокси со своим
    # заголовком. Ровно так и происходит с туннелем ngrok: он требует
    # `ngrok-skip-browser-warning`, браузер спрашивает разрешение на него
    # в preflight и получает 400, после чего ни один запрос не проходит.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(bot_router)
    app.include_router(api_router)
    app.include_router(catalog_router)
    app.include_router(personal_router)

    @app.get("/health", tags=["service"], summary="Проверка живости")
    async def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "env": settings.app_env,
            "bot_configured": bool(settings.bot_token),
            "webhook_secret_set": bool(settings.webhook_secret),
        }

    return app


app = create_app()
