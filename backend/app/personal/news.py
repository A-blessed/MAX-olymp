"""Лента «Новости», вычисляемая из дат этапов и прогресса.

Отдельно новости не хранятся: все пять категорий механики однозначно
выводятся из того, что уже есть в базе. Хранимая лента разъезжалась бы
с календарём при каждом обновлении дат из источника.

Категории:

* ``urgent``  — этап начинается или заканчивается сегодня;
* ``soon``    — начинается или заканчивается в ближайшие 7 дней;
* ``later``   — всё остальное впереди, включая этапы, идущие долго;
* ``awaiting_answer`` — этап завершён, а ответа «прошёл / не прошёл» нет;
* ``finished`` — завершённые этапы.

«Срочно» и «Скоро» требуют точного дня. Этап, о котором известен только
месяц, туда не попадает никогда — по той же причине, по которой у него
нет таймера: «через 3 дня» для «марта 2027» было бы выдумкой.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Dict, List, Optional, Sequence

from ..catalog.dates import Precision
from ..catalog.models import Olympiad, Stage
from ..catalog.presentation import StageStatus, stage_status
from .models import StageResult
from .rules import awaits_answer

SOON_DAYS = 7

_MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


class NewsCategory(str, Enum):
    URGENT = "urgent"
    SOON = "soon"
    LATER = "later"
    AWAITING_ANSWER = "awaiting_answer"
    FINISHED = "finished"


@dataclass
class NewsItem:
    category: NewsCategory
    olympiad_id: int
    olympiad_name: str
    subject_id: Optional[int]
    level: Optional[int]
    stage_id: int
    stage_name: str
    message: str
    # Дата, к которой привязано событие; для сортировки внутри категории.
    event_date: Optional[date]
    raw_date_range: Optional[str]
    result: Optional[StageResult] = None


@dataclass
class NewsFeed:
    urgent: List[NewsItem] = field(default_factory=list)
    soon: List[NewsItem] = field(default_factory=list)
    later: List[NewsItem] = field(default_factory=list)
    awaiting_answer: List[NewsItem] = field(default_factory=list)
    finished: List[NewsItem] = field(default_factory=list)

    def add(self, item: NewsItem) -> None:
        getattr(self, item.category.value).append(item)


def plural_days(count: int) -> str:
    """«1 день», «3 дня», «5 дней», «21 день», «12 дней»."""
    tail = count % 100
    if 11 <= tail <= 14:
        word = "дней"
    elif count % 10 == 1:
        word = "день"
    elif count % 10 in (2, 3, 4):
        word = "дня"
    else:
        word = "дней"
    return f"{count} {word}"


def _human_date(value: date) -> str:
    return f"{value.day} {_MONTHS_GENITIVE[value.month - 1]}"


def _is_exact(precision: Optional[Precision]) -> bool:
    return precision is Precision.DAY


def classify(
    stage: Stage,
    olympiad: Olympiad,
    *,
    result: Optional[StageResult],
    locked: bool,
    today: date,
) -> Optional[NewsItem]:
    """Определяет, в какую категорию попадает этап и что о нём сказать.

    ``None`` — этап в ленту не попадает: заблокирован ответом «не прошёл»
    на предыдущем или вовсе без дат.
    """
    if locked:
        return None

    status = stage_status(stage, today)
    if status is StageStatus.UNKNOWN:
        return None

    def item(category: NewsCategory, message: str, event_date: Optional[date]) -> NewsItem:
        return NewsItem(
            category=category,
            olympiad_id=olympiad.id,
            olympiad_name=olympiad.name,
            subject_id=olympiad.subject_id,
            level=olympiad.level,
            stage_id=stage.id,
            stage_name=stage.name,
            message=message,
            event_date=event_date,
            raw_date_range=stage.raw_date_range,
            result=result,
        )

    if status is StageStatus.FINISHED:
        if awaits_answer(stage, result, locked, today):
            return item(
                NewsCategory.AWAITING_ANSWER,
                f"Этап «{stage.name}» завершён. Ты прошёл(а) дальше?",
                stage.ends_on or stage.starts_on,
            )
        if result is StageResult.PASSED:
            outcome = " — ты прошёл(а) дальше"
        elif result is StageResult.FAILED:
            outcome = " — дальше не прошёл(а)"
        else:
            outcome = ""
        return item(
            NewsCategory.FINISHED,
            f"Этап «{stage.name}» завершён{outcome}",
            stage.ends_on or stage.starts_on,
        )

    exact_start = stage.starts_on if _is_exact(stage.start_precision) else None
    exact_end = stage.ends_on if _is_exact(stage.end_precision) else None
    horizon = today + timedelta(days=SOON_DAYS)

    if status is StageStatus.UPCOMING:
        if exact_start == today:
            return item(NewsCategory.URGENT, f"«{stage.name}» начинается сегодня", exact_start)
        if exact_start is not None and exact_start <= horizon:
            days = (exact_start - today).days
            return item(
                NewsCategory.SOON,
                f"«{stage.name}» начинается через {plural_days(days)}",
                exact_start,
            )
        if exact_start is not None:
            return item(
                NewsCategory.LATER,
                f"«{stage.name}» начнётся {_human_date(exact_start)}",
                exact_start,
            )
        # Известен только месяц — без обещаний про конкретный день.
        return item(
            NewsCategory.LATER,
            f"«{stage.name}»: {stage.raw_date_range or 'дата уточняется'}",
            stage.starts_on,
        )

    # Этап идёт.
    if exact_start == today:
        return item(NewsCategory.URGENT, f"«{stage.name}» начинается сегодня", exact_start)
    if exact_end == today:
        return item(NewsCategory.URGENT, f"«{stage.name}» заканчивается сегодня", exact_end)
    if exact_end is not None and exact_end <= horizon:
        days = (exact_end - today).days
        return item(
            NewsCategory.SOON,
            f"«{stage.name}» заканчивается через {plural_days(days)}",
            exact_end,
        )
    if exact_end is not None:
        return item(
            NewsCategory.LATER,
            f"«{stage.name}» идёт до {_human_date(exact_end)}",
            exact_end,
        )
    return item(
        NewsCategory.LATER,
        f"«{stage.name}» идёт: {stage.raw_date_range or 'дата окончания не указана'}",
        stage.ends_on or stage.starts_on,
    )


def build_feed(
    entries: Sequence[tuple],
    *,
    today: date,
) -> NewsFeed:
    """Собирает ленту.

    ``entries`` — кортежи ``(olympiad, stage, result, locked)`` по всем
    этапам сохранённых олимпиад.
    """
    feed = NewsFeed()
    for olympiad, stage, result, locked in entries:
        news = classify(stage, olympiad, result=result, locked=locked, today=today)
        if news is not None:
            feed.add(news)

    far_future = date.max
    for bucket in (feed.urgent, feed.soon, feed.later, feed.awaiting_answer):
        bucket.sort(key=lambda n: (n.event_date or far_future, n.olympiad_name))
    # В «Завершено» свежие сверху.
    feed.finished.sort(key=lambda n: (n.event_date or date.min), reverse=True)
    return feed
