"""Правила механики «Мои олимпиады» и календаря.

Чистые функции без базы: каждое правило из описания механики проверяется
тестом напрямую, а слой API только собирает данные и вызывает их.

Нарушение правила — не исключительная ситуация, а ожидаемый ответ
пользователю, поэтому у каждого есть стабильный код. Фронтенд
переключается по коду, а не по тексту сообщения.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, Optional, Sequence, Set, Tuple

from ..catalog.dates import Precision
from ..catalog.models import Stage, StageKind
from ..catalog.presentation import StageStatus, stage_status
from .models import StageResult

# «Пользователь может отметить галочкой до трёх доступных олимпиад в день».
DAILY_PLAN_LIMIT = 3


@dataclass
class RuleViolation(Exception):
    """Действие противоречит механике. ``status`` — HTTP-код ответа."""

    code: str
    message: str
    status: int = 409

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def _last_day_of_month(value: date) -> date:
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


def plan_window(stage: Stage) -> Optional[Tuple[date, date]]:
    """Дни, в которые этап можно поставить в календарь.

    ``None`` — если точный день начала неизвестен: календарь размечает
    конкретные даты, а «март 2027» на день не положишь.

    Конец окна: точная дата окончания; если известен только месяц
    окончания — последний день этого месяца; если конца нет — этап
    считается однодневным.
    """
    if stage.starts_on is None or stage.start_precision is not Precision.DAY:
        return None

    start = stage.starts_on
    if stage.ends_on is None:
        end = start
    elif stage.end_precision is Precision.MONTH:
        end = _last_day_of_month(stage.ends_on)
    else:
        end = stage.ends_on

    # В источнике встречаются перепутанные даты — не даём окну вывернуться.
    return (start, max(start, end))


def locked_stage_ids(
    stages: Sequence[Stage], results: Dict[int, StageResult]
) -> Set[int]:
    """Этапы, закрытые ответом «не прошёл» на одном из предыдущих.

    По механике «не прошёл» означает конец олимпиады: следующие этапы
    не показываются в календаре, и отвечать на них нельзя. Сам этап с
    ответом «не прошёл» не блокируется — ответ можно поменять.
    """
    ordered = sorted(stages, key=lambda s: s.position)
    for index, stage in enumerate(ordered):
        if results.get(stage.id) is StageResult.FAILED:
            return {later.id for later in ordered[index + 1 :]}
    return set()


def is_eliminated(results: Iterable[StageResult]) -> bool:
    """Олимпиада для пользователя закончилась ответом «не прошёл»."""
    return any(result is StageResult.FAILED for result in results)


def awaits_answer(
    stage: Stage,
    result: Optional[StageResult],
    locked: bool,
    today: date,
) -> bool:
    """Нужно ли спросить пользователя, прошёл ли он дальше.

    Спрашиваем о завершённых этапах без ответа. Регистрацию не трогаем:
    «прошёл ли ты регистрацию» — вопрос без смысла, её просто проходят.
    """
    if result is not None or locked or stage.kind is StageKind.REGISTRATION:
        return False
    return stage_status(stage, today) is StageStatus.FINISHED


def check_can_answer(
    stage: Stage,
    *,
    saved: bool,
    locked: bool,
    today: date,
) -> None:
    """Можно ли отметить этап как пройденный или нет.

    На уже идущий этап отвечать разрешено: отборочный часто пишут в
    начале окна, а результаты приходят до его закрытия. Запрещено только
    для этапа, который ещё не начался, — пройти его пока нельзя.
    """
    if not saved:
        raise RuleViolation(
            "not_saved",
            "Сначала добавьте олимпиаду в «Мои олимпиады»",
        )
    if locked:
        raise RuleViolation(
            "stage_locked",
            "Этап закрыт: на одном из предыдущих отмечено «не прошёл»",
        )
    if stage_status(stage, today) is StageStatus.UPCOMING:
        raise RuleViolation(
            "stage_not_started",
            "Этап ещё не начался — отвечать пока рано",
            status=422,
        )


def check_can_plan(
    stage: Stage,
    day: date,
    *,
    saved: bool,
    locked: bool,
    today: date,
    existing_plan: Optional[date],
    planned_that_day: int,
) -> None:
    """Можно ли запланировать этап на конкретный день.

    ``existing_plan`` — дата, на которую этот этап уже стоит, если стоит.
    ``planned_that_day`` — сколько этапов уже запланировано на ``day``,
    не считая этого.

    Порядок проверок — от самых фундаментальных к частным, чтобы
    пользователь получил самую полезную причину отказа.
    """
    if not saved:
        raise RuleViolation(
            "not_saved",
            "Сначала добавьте олимпиаду в «Мои олимпиады»",
        )
    if locked:
        raise RuleViolation(
            "stage_locked",
            "Этап закрыт: на одном из предыдущих отмечено «не прошёл»",
        )

    window = plan_window(stage)
    if window is None:
        raise RuleViolation(
            "not_plannable",
            "У этапа нет точной даты — в календарь его не поставить",
            status=422,
        )

    start, end = window
    if not (start <= day <= end):
        raise RuleViolation(
            "date_outside_stage",
            f"Этап проходит с {start:%d.%m.%Y} по {end:%d.%m.%Y}",
            status=422,
        )
    if day < today:
        raise RuleViolation(
            "date_in_past",
            "Нельзя запланировать на прошедший день",
            status=422,
        )

    if existing_plan == day:
        # Повторный запрос на ту же дату — не ошибка, а идемпотентный no-op.
        return
    if existing_plan is not None:
        # По механике такой этап показывается серым с замком: чтобы
        # перенести, сначала нужно снять отметку в другом дне.
        raise RuleViolation(
            "already_planned_other_day",
            f"Этап уже запланирован на {existing_plan:%d.%m.%Y} — сначала снимите ту отметку",
        )
    if planned_that_day >= DAILY_PLAN_LIMIT:
        raise RuleViolation(
            "day_limit_reached",
            f"На этот день уже запланировано {DAILY_PLAN_LIMIT} олимпиады — это максимум",
        )
