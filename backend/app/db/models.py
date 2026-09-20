"""Модели базы данных.

Здесь только то, что нужно любому мини-приложению MAX независимо от
бизнес-логики: кто к нам приходил и с кем бот может переписываться.
Таблицы предметной области добавляются отдельными модулями.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    """Пользователь MAX.

    Запись создаётся только из проверенных данных запуска, поэтому ``id``
    здесь всегда доверенный — он не приходит из тела запроса.
    """

    __tablename__ = "users"

    # ID в MAX — int64, обычный Integer не подойдёт.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    photo_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # Метка запуска из диплинка (?startapp=...), например реферальный код.
    start_param: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - отладочное представление
        return f"<User id={self.id} username={self.username!r}>"


class BotDialog(Base):
    """Диалог пользователя с ботом.

    Нужен, чтобы знать, кому бот вправе писать: отправлять сообщения можно
    только тем, кто запустил бота и не остановил его.
    """

    __tablename__ = "bot_dialogs"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    stopped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - отладочное представление
        return f"<BotDialog user_id={self.user_id} active={self.is_active}>"
