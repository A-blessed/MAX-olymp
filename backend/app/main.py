"""Точка входа бэкенда.

Один сервис обслуживает два контура сразу:

* ``/webhook`` — события бота, авторизация по секрету в заголовке;
* ``/api/*``   — мини-приложение, авторизация по подписи данных запуска.

Контуры разные и не должны путаться, но живут в одном процессе
сознательно: вебхук обязан быть доступен по HTTPS на порту 443, и держать
ради этого два публичных адреса с двумя сертификатами незачем. Один
домен — один сертификат.

Наружу сервис смотрит через nginx на ``my-olymp.ru``: он обеспечивает TLS
на 443, отдаёт статику мини-приложения и проксирует ``/api`` и
``/webhook`` сюда. Приложение слушает обычный HTTP внутри сети.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.catalog import router as catalog_router
from .api.personal import router as personal_router
from .api.router import router as api_router
from .bot.router import router as bot_router
from .config import get_settings
from .db.session import dispose_engine, get_engine
from .max_api.client import MaxApiClient

logger = logging.getLogger(__name__)


class NoCacheStaticFiles(StaticFiles):
    """Статика мини-приложения, которую браузер не оставляет у себя.

    MAX открывает приложение во встроенном браузере, и закэшированная
    версия переживает выкладку: пользователь остаётся на старом коде, а
    отладить это почти невозможно — на машине разработчика всё свежее.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Any:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


async def check_database(settings: Any) -> None:
    """Достучаться до базы один раз при старте и сказать, что вышло.

    Без этой проверки недоступная база проявляется только на первом
    запросе пользователя — полотном трейсбека из глубины SQLAlchemy, где
    настоящая причина («хост не резолвится») лежит в самой последней
    строке. Одна строка в логе старта заменяет это полотно.

    Падать не даём: база может подняться позже, а приложение должно
    отвечать на /health и отдавать мини-приложение в любом случае.
    """
    from sqlalchemy import text

    try:
        async with asyncio.timeout(5):
            async with get_engine().connect() as connection:
                await connection.execute(text("SELECT 1"))
    except asyncio.TimeoutError:
        logger.error(
            "База %s не ответила за 5 секунд. Запросы к API будут падать с 500.",
            settings.database_url_safe,
        )
    except Exception as exc:  # носитель ошибки — драйвер, тип заранее не известен
        logger.error(
            "Нет связи с базой %s: %s. Запросы к API будут падать с 500.",
            settings.database_url_safe,
            exc.__class__.__name__,
        )
        if isinstance(exc, ConnectionRefusedError):
            # Хост разрешился, но на порту тишина. Самый частый случай на
            # Windows: установщик Postgres занимает 5433, когда 5432 уже
            # занят, и делает это молча.
            logger.error(
                "Хост найден, но на указанном порту никто не слушает. Сверьте "
                "порт в DATABASE_URL с тем, что выбрал установщик Postgres: "
                "если 5432 был занят, он поднялся на 5433.",
            )
        elif settings.database_host == "db":
            logger.error(
                "Хост «db» — это имя сервиса в docker compose, вне контейнера он "
                "не существует. Укажите в DATABASE_URL адрес настоящей Postgres, "
                "например postgresql+asyncpg://postgres:пароль@localhost:5432/max_olymp",
            )
    else:
        logger.info("База %s отвечает", settings.database_url_safe)


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
    logger.info("Публичный адрес: %s, вебхук: %s", settings.public_origin, settings.webhook_url)

    if settings.frontend_available:
        logger.info("Мини-приложение отдаётся из %s", settings.frontend_path)
    else:
        logger.info(
            "Статика не отдаётся: в %s нет index.html. Это нормально, когда "
            "её отдаёт nginx; при запуске без него корень ответит 404 и "
            "мини-приложение в MAX не откроется.",
            settings.frontend_path,
        )

    await check_database(settings)

    if not settings.public_base_url_is_https:
        # MAX доставляет события только по https на 443 и не принимает
        # самоподписанные сертификаты: с таким адресом подписка не оформится.
        logger.warning(
            "PUBLIC_BASE_URL=%s — MAX принимает вебхук только по https. "
            "Подписка на события с таким адресом не оформится.",
            settings.public_base_url or "(пусто)",
        )

    if settings.bot_token:
        ca_files = settings.extra_ca_files()
        if ca_files:
            logger.info(
                "Сертификаты из %s: %s",
                settings.extra_ca_certs_path,
                ", ".join(path.name for path in ca_files),
            )
        else:
            # Печатаем разобранный абсолютный путь: относительный ни о чём не
            # говорит, а «/app/certs» на Windows означает C:\app\certs —
            # не тот каталог, в который файлы клали.
            logger.warning(
                "В каталоге %s нет сертификатов. Обращения к %s, скорее всего, "
                "упадут с ошибкой TLS: домен подписан сертификатом Минцифры.",
                settings.extra_ca_certs_path,
                settings.max_api_base_url,
            )
            foreign = settings.foreign_files_in_certs_dir()
            if foreign:
                logger.warning(
                    "Файлы в каталоге есть, но подходящих расширений среди них "
                    "нет: %s. Годятся только .crt, .pem и .cer — связку .p7b "
                    "нужно сначала разобрать на отдельные сертификаты.",
                    ", ".join(foreign),
                )
            elif not settings.extra_ca_certs_path.is_dir():
                logger.warning(
                    "Каталога %s не существует. Путь задаётся EXTRA_CA_CERTS_DIR "
                    "и считается от рабочего каталога.",
                    settings.extra_ca_certs_path,
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
        # Голое «токен не задан» стоило команде вечера отладки: токен лежал
        # в .env, но процесс запускали из другого каталога и файла не видел.
        # Поэтому говорим не только «нет», но и где искали.
        logger.warning("BOT_TOKEN не задан — вызовы MAX API недоступны")
        if settings.env_file_found:
            logger.warning(
                "Файл %s прочитан, но BOT_TOKEN в нём пуст или строка закомментирована.",
                settings.env_file_path,
            )
        else:
            logger.warning(
                "Файла %s нет. Путь считается от рабочего каталога, а не от каталога "
                "с кодом: либо запускайте из папки с .env, либо задайте BOT_TOKEN "
                "переменной окружения. Проверьте и имя файла — «.env.txt» не читается.",
                settings.env_file_path,
            )

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

    # На `my-olymp.ru` фронтенд и API живут на одном origin, так что в бою
    # CORS не участвует вовсе. Middleware остаётся для копий страницы,
    # открытых с другого адреса: GitHub Pages, локальный файл, отладочный
    # туннель. Список origin задаётся в CORS_ORIGINS.
    #
    # Заголовки разрешаем любые: жёсткий список тут не защита — доступ
    # ограничивают origin и подпись данных запуска, — зато он ломается,
    # как только между фронтендом и сервером появляется прокси со своим
    # заголовком.
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

    # Статика — последней: путь "/" совпадает с чем угодно, и всё, что
    # объявлено выше, должно попасть в маршрут раньше. Порядок здесь не
    # стилистический, от него зависит, работает ли API.
    #
    # Каталога нет — раздача просто выключается. Так и устроен запуск в
    # Docker: там статику отдаёт nginx, а в образ она не копируется.
    if settings.frontend_available:
        app.mount(
            "/",
            NoCacheStaticFiles(directory=settings.frontend_path, html=True),
            name="frontend",
        )

    return app


app = create_app()
