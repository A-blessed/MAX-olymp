"""Настройки приложения. Всё читается из переменных окружения.

Ни одного секрета в коде: токен бота и секрет вебхука приходят только
из окружения (локально — из файла .env, который не попадает в git).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Окружение ---
    app_env: str = Field(default="development", description="development | production")
    log_level: str = Field(default="INFO")
    app_timezone: str = Field(
        default="Europe/Moscow",
        description="Часовой пояс, в котором считается «сегодня» для этапов и новостей.",
    )

    # --- MAX ---
    bot_token: str = Field(
        default="",
        description="Токен чат-бота. Выдаётся организаторами / в кабинете партнёров.",
    )
    max_api_base_url: str = Field(
        default="https://platform-api2.max.ru",
        description="Старый platform-api.max.ru больше не обслуживает ботов.",
    )
    max_api_timeout: float = Field(default=15.0)
    bot_username: str = Field(
        default="",
        description="Ник бота для диплинка https://max.ru/<botName>?startapp=...",
    )

    # --- Вебхук ---
    public_base_url: str = Field(
        default="https://my-olymp.ru",
        description=(
            "Публичный HTTPS-адрес бэкенда. Постоянный домен проекта — "
            "https://my-olymp.ru. Переопределяется в .env, если бэкенд "
            "поднят на туннеле для отладки."
        ),
    )
    webhook_path: str = Field(default="/webhook")
    webhook_secret: str = Field(
        default="",
        description="Приходит в заголовке X-Max-Bot-Api-Secret. 5-256 символов [A-Za-z0-9_-].",
    )

    # --- Мини-приложение ---
    launch_data_ttl: int = Field(
        default=86400,
        description="Максимальный возраст auth_date в секундах. 0 отключает проверку.",
    )
    cors_origins: str = Field(
        default="https://my-olymp.ru",
        description=(
            "Список origin фронтенда через запятую. Фронтенд отдаётся с того "
            "же домена, так что кросс-доменных запросов в бою нет; список "
            "нужен для копий страницы, открытых с другого адреса."
        ),
    )

    # --- База данных ---
    database_url: str = Field(
        default="postgresql+asyncpg://app:app@db:5432/app",
    )

    # --- TLS ---
    extra_ca_certs_dir: str = Field(
        default="/app/certs",
        description="Каталог с дополнительными корневыми сертификатами (Минцифры).",
    )

    @property
    def public_origin(self) -> str:
        """Публичный адрес без завершающего слеша."""
        return self.public_base_url.rstrip("/")

    @property
    def webhook_url(self) -> str:
        """Полный адрес вебхука для регистрации в MAX."""
        return f"{self.public_origin}{self.webhook_path}"

    @property
    def public_base_url_is_https(self) -> bool:
        """MAX принимает вебхук только по https и только на 443."""
        return self.public_origin.lower().startswith("https://")

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def launch_data_ttl_or_none(self) -> Optional[int]:
        return self.launch_data_ttl if self.launch_data_ttl > 0 else None

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    def extra_ca_files(self) -> List[Path]:
        """Список файлов сертификатов, которые нужно добавить в доверенные."""
        directory = Path(self.extra_ca_certs_dir)
        if not directory.is_dir():
            return []
        return sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in {".crt", ".pem", ".cer"}
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
