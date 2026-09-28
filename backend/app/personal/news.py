"""Лента «Новости», вычисляемая из дат этапов и прогресса.

Отдельно новости не хранятся: все категории механики однозначно выводятся
из того, что уже есть в базе. Хранимая лента разъезжалась бы с календарём
при каждом обновлении дат из источника.

Категории:

* ``urgent``  — этап начинается или заканчивается сегодня;
* ``soon``    — начинается или заканчивается в ближайшие 7 дней;
* ``later``   — всё остальное впереди, включая этапы, идущие долго;
* ``awaiting_answer`` — этап завершён, а ответа «прошёл / не прошёл» нет;
* ``finished`` — завершённые этапы;
* ``dates_added`` — у этапа появились даты, пока олимпиада была в «Моих».

Первые пять делят этапы между собой: каждый этап — ровно в одной.
``dates_added`` идёт поверх них: этап с новыми датами остаётся и в своей
категории, например в «Скоро».

«Срочно» и «Скоро» требуют точного дня. Этап, о котором известен только
месяц, туда не попадает никогда — по той же причине, по которой у него
нет таймера: «через 3 дня» для «марта 2027» было бы выдумкой.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Sequence

from ..catalog.dates import Precision
from ..catalog.models import Olympiad, Stage
from ..catalog.presentation import (
    DatePrecision,
    StageStatus,
    date_precision,
    stage_bounds,
    stage_status,
)
from .models import StageResult
from .rules import awaits_answer, plan_window

SOON_DAYS = 7

AWAITING_MESSAGE = "Подтверди, прошёл ли ты в следующий этап"
AWAITING_BADGE = "Ожидает ответа"
DATES_ADDED_MESSAGE = "Появились даты этапа"
DATES_ADDED_BADGE = "Появились даты"

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
    DATES_ADDED = "dates_added"


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
    subject_name: Optional[str] = None
    badge: Optional[str] = None
    # Последний день, когда этап можно было поставить в календарь.
    plan_window_end: Optional[date] = None
    # Даты этапа словами: «25 сентября – 15 октября 2026».
    date_range: Optional[str] = None
    # Когда случилось событие — сейчас только у «Появились даты».
    created_at: Optional[datetime] = None


@dataclass
class NewsFeed:
    urgent: List[NewsItem] = field(default_factory=list)
    soon: List[NewsItem] = field(default_factory=list)
    later: List[NewsItem] = field(default_factory=list)
    awaiting_answer: List[NewsItem] = field(default_factory=list)
    finished: List[NewsItem] = field(default_factory=list)
    dates_added: List[NewsItem] = field(default_factory=list)

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


def _full_date(value: date) -> str:
    return f"{_human_date(value)} {value.year}"


def human_date_range(stage: Stage) -> Optional[str]:
    """Даты этапа словами — те же, что рисует календарь.

    «4–17 декабря 2026», «25 сентября – 15 октября 2026», «4 октября 2026»,
    «до 18 ноября 2026». ``None``, если точного дня нет: для «марта 2027»
    есть ``raw_date_range``.
    """
    if date_precision(stage) is DatePrecision.UNKNOWN:
        return None
    start, end = stage_bounds(stage)
    if start is None:
        return f"до {_full_date(end)}"
    if end is None or end == start:
        return _full_date(start)
    if start.year != end.year:
        return f"{_full_date(start)} – {_full_date(end)}"
    if start.month != end.month:
        return f"{_human_date(start)} – {_full_date(end)}"
    return f"{start.day}–{_full_date(end)}"


def _is_exact(precision: Optional[Precision]) -> bool:
    return precision is Precision.DAY


def _news_item(
    stage: Stage,
    olympiad: Olympiad,
    category: NewsCategory,
    message: str,
    event_date: Optional[date],
    *,
    result: Optional[StageResult] = None,
) -> NewsItem:
    subject = olympiad.subject
    return NewsItem(
        category=category,
        olympiad_id=olympiad.id,
        olympiad_name=olympiad.name,
        subject_id=olympiad.subject_id,
        subject_name=subject.name if subject is not None else None,
        level=olympiad.level,
        stage_id=stage.id,
        stage_name=stage.name,
        message=message,
        event_date=event_date,
        raw_date_range=stage.raw_date_range,
        date_range=human_date_range(stage),
        result=result,
    )


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
        return _news_item(stage, olympiad, category, message, event_date, result=result)

    if status is StageStatus.FINISHED:
        if awaits_answer(stage, result, locked, today):
            # Кнопки «Я прошёл(а) / Я не прошёл(а)» фронтенд рисует по stage_id.
            news = item(NewsCategory.AWAITING_ANSWER, AWAITING_MESSAGE,
                        stage.ends_on or stage.starts_on)
            window = plan_window(stage)
            news.plan_window_end = window[1] if window else None
            news.badge = AWAITING_BADGE
            return news
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


def dates_added(
    stage: Stage,
    olympiad: Olympiad,
    *,
    locked: bool,
    today: date,
    saved_at: Optional[datetime] = None,
) -> Optional[NewsItem]:
    """Новость «Появились даты», если она есть у этапа.

    Даты должны появиться, пока олимпиада уже была в «Моих» (``saved_at``):
    кто добавил её с готовыми датами, тот их и так видел. Иначе после
    первого импорта в пустую базу новостью стал бы каждый этап.

    Новость уходит, когда этап завершился или закрыт ответом «не прошёл» —
    дальше она ни к чему не зовёт. И когда даты снова пропали: показывать
    было бы нечего.
    """
    added = stage.dates_added_at
    if added is None or locked:
        return None
    if saved_at is not None and added < saved_at:
        return None
    if date_precision(stage) is DatePrecision.UNKNOWN:
        return None
    if stage_status(stage, today) is StageStatus.FINISHED:
        return None

    start, end = stage_bounds(stage)
    news = _news_item(stage, olympiad, NewsCategory.DATES_ADDED, DATES_ADDED_MESSAGE, start or end)
    news.badge = DATES_ADDED_BADGE
    news.created_at = added
    return news


def build_feed(
    entries: Sequence[tuple],
    *,
    today: date,
    saved_at: Optional[Dict[int, datetime]] = None,
) -> NewsFeed:
    """Собирает ленту.

    ``entries`` — кортежи ``(olympiad, stage, result, locked)`` по всем
    этапам сохранённых олимпиад. ``saved_at`` — когда каждая из них
    добавлена в «Мои», по id олимпиады.
    """
    saved_at = saved_at or {}
    feed = NewsFeed()
    for olympiad, stage, result, locked in entries:
        news = classify(stage, olympiad, result=result, locked=locked, today=today)
        if news is not None:
            feed.add(news)
        fresh = dates_added(
            stage, olympiad, locked=locked, today=today, saved_at=saved_at.get(olympiad.id)
        )
        if fresh is not None:
            feed.add(fresh)

    far_future = date.max
    for bucket in (feed.urgent, feed.soon, feed.later):
        bucket.sort(key=lambda n: (n.event_date or far_future, n.olympiad_name))
    # Дольше всех ждущие ответа — сверху.
    feed.awaiting_answer.sort(
        key=lambda n: (n.plan_window_end or n.event_date or far_future, n.olympiad_name)
    )
    # В «Завершено» свежие сверху.
    feed.finished.sort(key=lambda n: (n.event_date or date.min), reverse=True)
    # «Появились даты»: сначала новые, среди одновременных — ближайшие этапы.
    feed.dates_added.sort(
        key=lambda n: (-n.created_at.timestamp(), n.event_date or far_future, n.olympiad_name)
    )
    return feed
