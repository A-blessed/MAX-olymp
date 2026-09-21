"""Единое понятие «сегодня» для всего приложения.

Сервер живёт в UTC, а пользователи — в Москве и восточнее. Для Москвы с
полуночи до трёх ночи UTC-дата ещё вчерашняя: этап, начинающийся сегодня,
выпал бы из «Срочно», а таймер показал бы на день больше. Поэтому всё,
что зависит от календарной даты, берёт её отсюда, а не из date.today().
"""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from .config import get_settings


@lru_cache
def app_timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().app_timezone)


def today() -> date:
    """Сегодняшняя дата в часовом поясе приложения."""
    return datetime.now(app_timezone()).date()
