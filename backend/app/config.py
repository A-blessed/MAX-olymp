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


# Расширения, в которых ожидается сертификат в виде PEM или DER.
CA_CERT_SUFFIXES = {".crt", ".pem", ".cer"}


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

    # --- Мини-приложение: статика ---
    frontend_dir: str = Field(
        default="frontend",
        description=(
            "Каталог с файлами мини-приложения. Считается от рабочего каталога. "
            "Если каталога нет, раздача выключается: так и происходит в Docker, "
            "где статику отдаёт nginx. Пустое значение выключает раздачу явно."
        ),
    )

    # --- База данных ---
    database_url: str = Field(
        default="postgresql+asyncpg://app:app@db:5432/app",
    )

    # --- TLS ---
    extra_ca_certs_dir: str = Field(
        default="certs",
        description=(
            "Каталог с корневыми сертификатами Минцифры. Путь относительный — "
            "считается от рабочего каталога. Абсолютный /app/certs задают оба "
            "compose-файла: внутри контейнера каталог именно там, а на Windows "
            "такой путь уехал бы в C:\\app\\certs."
        ),
    )

    @property
    def env_file_path(self) -> Path:
        """Куда приложение смотрит за файлом .env.

        Путь считается от рабочего каталога процесса, а не от каталога с
        кодом: запуск из другой папки — самая частая причина того, что
        настройки «не подхватились».
        """
        return Path(".env").resolve()

    @property
    def env_file_found(self) -> bool:
        return self.env_file_path.is_file()

    @property
    def frontend_path(self) -> Path:
        return Path(self.frontend_dir).resolve()

    @property
    def frontend_available(self) -> bool:
        """Есть ли что отдавать: каталог с index.html внутри."""
        if not self.frontend_dir.strip():
            return False
        return (self.frontend_path / "index.html").is_file()

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

    @property
    def extra_ca_certs_path(self) -> Path:
        """Абсолютный путь к каталогу сертификатов.

        Сообщать в лог нужно именно его: относительный путь ничего не
        говорит, а «/app/certs» на Windows и вовсе означает не тот каталог,
        в который пользователь клал файлы.
        """
        return Path(self.extra_ca_certs_dir).resolve()

    def extra_ca_files(self) -> List[Path]:
        """Список файлов сертификатов, которые нужно добавить в доверенные."""
        directory = self.extra_ca_certs_path
        if not directory.is_dir():
            return []
        return sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in CA_CERT_SUFFIXES
        )

    def foreign_files_in_certs_dir(self) -> List[str]:
        """Файлы в каталоге, которые не будут подхвачены из-за расширения.

        Отдельный случай: с Госуслуг сертификаты нередко скачиваются одним
        файлом .p7b, а он сюда не годится — его нужно сначала разобрать.
        Без этой подсказки каталог выглядит наполненным, а сертификатов нет.
        """
        directory = self.extra_ca_certs_path
        if not directory.is_dir():
            return []
        return sorted(
            path.name
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() not in CA_CERT_SUFFIXES
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
