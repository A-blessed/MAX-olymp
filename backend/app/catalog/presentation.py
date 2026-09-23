"""Приведение данных каталога к виду, удобному интерфейсу.

Отдельный слой нужен из-за точности дат. В базе лежит дата и признак
точности; интерфейсу же нужен готовый ответ на вопрос «сколько осталось»
и «идёт ли этап сейчас». Для этапа, у которого известен только месяц,
честный ответ — «неизвестно», и он должен быть выражен явным ``null``,
а не нулём или выдуманным числом.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Iterable, Optional

from .dates import Precision
from .models import Stage


class StageStatus(str, Enum):
    """Положение этапа относительно сегодняшнего дня."""

    UPCOMING = "upcoming"
    ACTIVE = "active"
    FINISHED = "finished"
    UNKNOWN = "unknown"


def _month_key(value: date) -> int:
    return value.year * 12 + value.month


def _starts_after(value: date, precision: Optional[Precision], today: date) -> bool:
    """Начало ещё впереди?

    При точности до месяца сравниваем месяцами: этап «март 2027» не
    считается начавшимся, пока не наступил март 2027.
    """
    if precision is Precision.MONTH:
        return _month_key(value) > _month_key(today)
    return value > today


def _ends_before(value: date, precision: Optional[Precision], today: date) -> bool:
    if precision is Precision.MONTH:
        return _month_key(value) < _month_key(today)
    return value < today


def stage_status(stage: Stage, today: Optional[date] = None) -> StageStatus:
    """Определяет, предстоит этап, идёт или закончился."""
    today = today or date.today()

    if stage.starts_on is None and stage.ends_on is None:
        return StageStatus.UNKNOWN

    if stage.starts_on is not None and _starts_after(
        stage.starts_on, stage.start_precision, today
    ):
        return StageStatus.UPCOMING

    if stage.ends_on is not None:
        if _ends_before(stage.ends_on, stage.end_precision, today):
            return StageStatus.FINISHED
        return StageStatus.ACTIVE

    # Начало наступило, конец неизвестен — считаем идущим только в день
    # начала, дальше судить не о чем.
    if stage.starts_on == today:
        return StageStatus.ACTIVE
    return StageStatus.FINISHED if stage.start_precision is Precision.DAY else StageStatus.UNKNOWN


def days_until_start(stage: Stage, today: Optional[date] = None) -> Optional[int]:
    """Сколько дней до начала. ``None``, если точного дня нет.

    Интерфейс обязан обработать ``None`` отдельно: вместо таймера
    показать исходную строку вроде «март 2027».
    """
    if stage.starts_on is None or stage.start_precision is not Precision.DAY:
        return None
    return (stage.starts_on - (today or date.today())).days


def is_plannable(stage: Stage) -> bool:
    """Можно ли поставить этап в календарь по дням.

    Календарь размечает конкретные даты, поэтому этап, у которого известен
    только месяц, в него попасть не может.
    """
    return stage.starts_on is not None and stage.start_precision is Precision.DAY


def pick_next_stage(stages: Iterable[Stage], today: Optional[date] = None) -> Optional[Stage]:
    """Ближайший идущий или предстоящий этап — для подписи на карточке.

    Этапы без точного дня участвуют, но уступают точным: подпись
    «до этапа N дней» полезнее, чем «март 2027».
    """
    today = today or date.today()
    candidates = list(stages)

    active = [s for s in candidates if stage_status(s, today) is StageStatus.ACTIVE]
    if active:
        return min(active, key=lambda s: s.position)

    upcoming = [
        s
        for s in candidates
        if stage_status(s, today) is StageStatus.UPCOMING and s.starts_on is not None
    ]
    if not upcoming:
        return None
    return min(upcoming, key=lambda s: (not is_plannable(s), s.starts_on, s.position))
