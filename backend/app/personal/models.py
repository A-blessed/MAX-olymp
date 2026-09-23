"""Модели пользовательской части.

Всё лежит в отдельных таблицах, а не в новых колонках `users` или
`stages`: схема создаётся через create_all, который добавляет недостающие
таблицы, но не умеет менять существующие. Новая колонка в старой таблице
на уже развёрнутой базе просто не появилась бы.

Хранить это на сервере, а не в браузере, обязывает механика: напоминания
шлёт бот, и он должен знать, за чем следит пользователь, даже когда
мини-приложение закрыто.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    SmallInteger,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.models import Base


class StageResult(str, Enum):
    """Ответ пользователя на вопрос «прошёл ли ты дальше»."""

    PASSED = "passed"
    FAILED = "failed"


class UserSettings(Base):
    """Настройки из вкладки «Мои олимпиады».

    Запись создаётся лениво, при первом обращении: значения по умолчанию
    совпадают с механикой — уведомления включены, режим для дальтоников
    выключен.
    """

    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    grade: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    colorblind_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SavedOlympiad(Base):
    """Олимпиада, на которую пользователь нажал «Буду писать»."""

    __tablename__ = "saved_olympiads"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    olympiad_id: Mapped[int] = mapped_column(
        ForeignKey("olympiads.id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StageProgress(Base):
    """Ответ «прошёл / не прошёл» по конкретному этапу.

    «Не прошёл» завершает олимпиаду для пользователя: последующие этапы
    блокируются и пропадают из календаря.
    """

    __tablename__ = "stage_progress"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    stage_id: Mapped[int] = mapped_column(
        ForeignKey("stages.id", ondelete="CASCADE"), primary_key=True
    )
    result: Mapped[StageResult] = mapped_column(
        SAEnum(
            StageResult,
            name="stage_result",
            values_callable=lambda cls: [item.value for item in cls],
        ),
        nullable=False,
    )
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StagePlan(Base):
    """День, в который пользователь собирается писать этап.

    Один этап — одна дата: первичный ключ (user_id, stage_id) это и
    выражает. Лимит «не больше трёх в день» проверяется в сервисе.
    """

    __tablename__ = "stage_plans"
    __table_args__ = (
        # Под проверку лимита на день и выборку календаря за период.
        Index("ix_stage_plans_user_day", "user_id", "planned_on"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    stage_id: Mapped[int] = mapped_column(
        ForeignKey("stages.id", ondelete="CASCADE"), primary_key=True
    )
    planned_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
