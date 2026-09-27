"""Утренние напоминания: что сказать пользователю.

Бот пишет раз в день, одной сводкой. Отдельное сообщение на каждое
событие быстро превращается в шум: у школьника, следящего за пятью
олимпиадами, в сезон набегает по несколько событий в день, и десяток
уведомлений он просто выключит. Одну сводку утром он прочтёт.

В сводку попадает только то, что привязано к точному дню, — по той же
причине, по которой у этапа «март 2027» нет таймера: «начинается завтра»
про дату, известную до месяца, было бы выдумкой.

Что напоминаем, в порядке важности — у одного этапа в сводке не больше
одной строки, и берётся первая подходящая:

    сегодня  — запланированный на сегодня этап, начало, последний день;
    завтра   — то же про завтра;
    скоро    — последний день через ``DEADLINE_HEADS_UP_DAYS`` дня:
               хватит времени доделать работу, а не узнать о сроке в
               последний вечер;
    вопрос   — этап закончился вчера, а ответа «прошёл / не прошёл» нет:
               от него зависит, какие этапы останутся в календаре.

Ничего из этого нет — сообщения нет вовсе. Пустая сводка «сегодня ничего»
приучает не открывать сообщения бота.

Модуль чистый: ни базы, ни сети. Расчёт проверяется тестами напрямую, а
рассылка только собирает данные и вызывает его.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from ..catalog.dates import Precision
from ..catalog.models import Olympiad, Stage
from ..catalog.presentation import StageStatus, stage_status
from ..max_api.client import MAX_TEXT_LENGTH
from .models import StageResult
from .news import _human_date as human_date
from .news import plural_days
from .rules import awaits_answer

# За сколько дней до последнего дня этапа предупреждать заранее.
DEADLINE_HEADS_UP_DAYS = 3

# Сколько строк показываем в одной сводке. Остальное — в приложении:
# сообщение на экран длиной во весь календарь никто не дочитает.
MAX_ITEMS = 12


class Section(str, Enum):
    """Блок сводки. Порядок объявления — порядок вывода."""

    TODAY = "today"
    TOMORROW = "tomorrow"
    SOON = "soon"
    ASK = "ask"


class ReminderKind(str, Enum):
    PLANNED_TODAY = "planned_today"
    STARTS_TODAY = "starts_today"
    ENDS_TODAY = "ends_today"
    PLANNED_TOMORROW = "planned_tomorrow"
    STARTS_TOMORROW = "starts_tomorrow"
    ENDS_TOMORROW = "ends_tomorrow"
    ENDS_SOON = "ends_soon"
    ASK_RESULT = "ask_result"

    @property
    def section(self) -> Section:
        return _SECTION_OF[self]


_SECTION_OF = {
    ReminderKind.PLANNED_TODAY: Section.TODAY,
    ReminderKind.STARTS_TODAY: Section.TODAY,
    ReminderKind.ENDS_TODAY: Section.TODAY,
    ReminderKind.PLANNED_TOMORROW: Section.TOMORROW,
    ReminderKind.STARTS_TOMORROW: Section.TOMORROW,
    ReminderKind.ENDS_TOMORROW: Section.TOMORROW,
    ReminderKind.ENDS_SOON: Section.SOON,
    ReminderKind.ASK_RESULT: Section.ASK,
}

_SECTION_ORDER = {section: index for index, section in enumerate(Section)}


@dataclass(frozen=True)
class ReminderItem:
    kind: ReminderKind
    stage_id: int
    stage_name: str
    olympiad_name: str
    subject_name: Optional[str]
    # День, к которому относится событие: для сортировки внутри блока.
    day: date


def _exact(value: Optional[date], precision: Optional[Precision]) -> Optional[date]:
    return value if value is not None and precision is Precision.DAY else None


def reminder_for(
    stage: Stage,
    olympiad: Olympiad,
    *,
    result: Optional[StageResult],
    locked: bool,
    planned_on: Optional[date],
    today: date,
) -> Optional[ReminderItem]:
    """Что сказать про этап сегодня утром. ``None`` — ничего."""
    # Этап закрыт ответом «не прошёл» на предыдущем — напоминать не о чем.
    # Ответ на сам этап тоже означает, что он для пользователя позади:
    # отвечать разрешено и на идущий этап, если его уже написали.
    if locked or result is not None:
        return None

    status = stage_status(stage, today)
    if status is StageStatus.UNKNOWN:
        return None

    start = _exact(stage.starts_on, stage.start_precision)
    end = _exact(stage.ends_on, stage.end_precision)
    tomorrow = today + timedelta(days=1)
    soon = today + timedelta(days=DEADLINE_HEADS_UP_DAYS)

    # «Последний день» говорим только про идущий этап — сюда же относится
    # дедлайн без начала. Про этап, который ещё не начался, «заканчивается
    # через 3 дня» звучит как ошибка. Статус берём общий с приложением: он
    # правильно понимает и начало, известное лишь до месяца.
    started = status is StageStatus.ACTIVE

    def item(kind: ReminderKind, day: date) -> ReminderItem:
        subject = olympiad.subject.name if olympiad.subject is not None else None
        return ReminderItem(
            kind=kind,
            stage_id=stage.id,
            stage_name=stage.name,
            olympiad_name=olympiad.name,
            subject_name=subject,
            day=day,
        )

    if status is StageStatus.FINISHED:
        last_day = end or (start if stage.ends_on is None else None)
        yesterday = today - timedelta(days=1)
        if last_day == yesterday and awaits_answer(stage, result, locked, today):
            return item(ReminderKind.ASK_RESULT, last_day)
        return None

    if planned_on == today:
        return item(ReminderKind.PLANNED_TODAY, today)
    if start == today:
        return item(ReminderKind.STARTS_TODAY, today)
    if end == today and started:
        return item(ReminderKind.ENDS_TODAY, today)
    if planned_on == tomorrow:
        return item(ReminderKind.PLANNED_TOMORROW, tomorrow)
    if start == tomorrow:
        return item(ReminderKind.STARTS_TOMORROW, tomorrow)
    if end == tomorrow and started:
        return item(ReminderKind.ENDS_TOMORROW, tomorrow)
    if end == soon and started:
        return item(ReminderKind.ENDS_SOON, soon)
    return None


def collect_reminders(
    entries: Sequence[Tuple[Olympiad, Stage, Optional[StageResult], bool]],
    plans: Dict[int, date],
    today: date,
) -> List[ReminderItem]:
    """Все напоминания пользователя на сегодня, в порядке вывода.

    ``entries`` — кортежи ``(olympiad, stage, result, locked)`` по всем
    этапам сохранённых олимпиад, те же, из которых строится лента.
    """
    items = []
    for olympiad, stage, result, locked in entries:
        reminder = reminder_for(
            stage,
            olympiad,
            result=result,
            locked=locked,
            planned_on=plans.get(stage.id),
            today=today,
        )
        if reminder is not None:
            items.append(reminder)

    items.sort(key=lambda r: (_SECTION_ORDER[r.kind.section], r.day, r.olympiad_name, r.stage_name))
    return items


_SECTION_TITLE = {
    Section.TODAY: "Сегодня",
    Section.TOMORROW: "Завтра",
    Section.SOON: f"Через {plural_days(DEADLINE_HEADS_UP_DAYS)}",
    Section.ASK: "Как прошло?",
}

_LINE = {
    ReminderKind.PLANNED_TODAY: "По плану: «{stage}»",
    ReminderKind.STARTS_TODAY: "Начинается «{stage}»",
    ReminderKind.ENDS_TODAY: "Последний день: «{stage}»",
    ReminderKind.PLANNED_TOMORROW: "По плану: «{stage}»",
    ReminderKind.STARTS_TOMORROW: "Начинается «{stage}»",
    ReminderKind.ENDS_TOMORROW: "Последний день: «{stage}»",
    ReminderKind.ENDS_SOON: "Заканчивается «{stage}»",
    ReminderKind.ASK_RESULT: "«{stage}»",
}

_ASK_FOOTER = (
    "Отметь в приложении, прошёл ли ты дальше: от этого зависит, "
    "какие этапы останутся в календаре."
)


def _line(item: ReminderItem) -> str:
    head = _LINE[item.kind].format(stage=item.stage_name)
    subject = f" ({item.subject_name})" if item.subject_name else ""
    return f"• {head} — {item.olympiad_name}{subject}"


def _compose(items: Sequence[ReminderItem], today: date, hidden: int) -> str:
    lines = [f"Привет! Что важно на {human_date(today)}:"]
    current = None
    for item in items:
        section = item.kind.section
        if section is not current:
            if current is Section.ASK:
                lines.append(_ASK_FOOTER)
            lines.append("")
            lines.append(_SECTION_TITLE[section])
            current = section
        lines.append(_line(item))
    if current is Section.ASK:
        lines.append(_ASK_FOOTER)
    if hidden:
        lines.append("")
        lines.append(f"И ещё {hidden} — в приложении.")
    return "\n".join(lines)


def render_digest(items: Sequence[ReminderItem], today: date) -> Optional[str]:
    """Текст сводки. ``None``, если сказать нечего — тогда и писать не надо."""
    if not items:
        return None

    shown = list(items[:MAX_ITEMS])
    text = _compose(shown, today, hidden=len(items) - len(shown))
    # Длинные названия олимпиад встречаются, и дюжина таких может не
    # влезть в лимит сообщения. Тогда показываем меньше, а не режем текст
    # посреди слова: хвост уходит в «и ещё N — в приложении».
    while len(text) > MAX_TEXT_LENGTH and len(shown) > 1:
        shown.pop()
        text = _compose(shown, today, hidden=len(items) - len(shown))
    return text[:MAX_TEXT_LENGTH]
