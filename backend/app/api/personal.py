"""Эндпоинты пользовательской части.

Мои олимпиады, прогресс по этапам, календарь, настройки и новости. Все
правила механики живут в ``personal/rules.py``; здесь только загрузка
данных, вызов правил и запись.

Договорённости с фронтендом:

* ошибка приходит как ``{"detail": {"code": ..., "message": ...}}`` —
  переключаться нужно по ``code``, текст предназначен для показа;
* любое изменение этапа (ответ «прошёл / не прошёл», план в календаре)
  возвращает актуальное состояние всей олимпиады: ответ «не прошёл»
  блокирует последующие этапы, и интерфейсу нужно увидеть это сразу.
"""

from __future__ import annotations

import calendar as pycalendar
from datetime import date, datetime
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..catalog.models import Olympiad, Stage, StageKind
from ..catalog.presentation import pick_next_stage
from ..clock import today as app_today
from ..db.models import User
from ..db.session import get_session
from ..personal.models import (
    SavedOlympiad,
    StagePlan,
    StageProgress,
    StageResult,
    UserSettings,
)
from ..personal.news import NewsItem, build_feed
from ..personal.rules import (
    DAILY_PLAN_LIMIT,
    RuleViolation,
    awaits_answer,
    check_can_answer,
    check_can_plan,
    is_eliminated,
    locked_stage_ids,
    plan_window,
)
from ..security.deps import get_current_user
from .catalog import StageOut, SubjectOut

router = APIRouter(prefix="/api/me", tags=["personal"])

# Ограничение на запрос календаря: год с запасом покрывает любой вид.
MAX_CALENDAR_SPAN_DAYS = 400


# ---------------------------------------------------------------------
# Схемы
# ---------------------------------------------------------------------


class SettingsOut(BaseModel):
    grade: Optional[int] = None
    notifications_enabled: bool = True
    colorblind_mode: bool = False


class SettingsPatch(BaseModel):
    """Частичное обновление: изменяются только переданные поля.

    ``grade: null`` явно сбрасывает класс.
    """

    grade: Optional[int] = Field(default=None, ge=1, le=11)
    notifications_enabled: Optional[bool] = None
    colorblind_mode: Optional[bool] = None


class MyStageOut(StageOut):
    """Этап глазами конкретного пользователя."""

    result: Optional[StageResult] = None
    # «Запланировано на _ число» из механики.
    planned_on: Optional[date] = None
    # Закрыт ответом «не прошёл» на одном из предыдущих этапов.
    locked: bool = False
    # Этап завершён и ждёт ответа «прошёл / не прошёл».
    awaiting_answer: bool = False
    # В какие дни этап можно поставить в календарь.
    plan_window_start: Optional[date] = None
    plan_window_end: Optional[date] = None

    @classmethod
    def build_personal(
        cls,
        stage: Stage,
        today: date,
        *,
        result: Optional[StageResult],
        planned_on: Optional[date],
        locked: bool,
    ) -> "MyStageOut":
        data = StageOut.build(stage, today).model_dump()
        # Для пользователя заблокированный этап планировать нельзя, даже
        # если у него есть точная дата.
        data["plannable"] = data["plannable"] and not locked
        window = plan_window(stage)
        return cls(
            **data,
            result=result,
            planned_on=planned_on,
            locked=locked,
            awaiting_answer=awaits_answer(stage, result, locked, today),
            plan_window_start=window[0] if window else None,
            plan_window_end=window[1] if window else None,
        )


class MyOlympiadOut(BaseModel):
    id: int
    name: str
    level: Optional[int] = None
    levels: List[int] = Field(default_factory=list)
    summary: Optional[str] = None
    grade_min: Optional[int] = None
    grade_max: Optional[int] = None
    subject_id: Optional[int] = None
    subject_name: Optional[str] = None
    subject: Optional[SubjectOut] = None
    grades: Optional[str] = None
    partner_universities: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None
    official_url: Optional[str] = None
    organizers: Optional[str] = None
    added_at: datetime
    # Ответ «не прошёл» — олимпиада серая и уходит вниз списка.
    eliminated: bool = False
    next_stage: Optional[MyStageOut] = None
    stages: List[MyStageOut] = Field(default_factory=list)


class MyOlympiadList(BaseModel):
    items: List[MyOlympiadOut]
    total: int


class SaveOut(BaseModel):
    olympiad_id: int
    saved: bool
    added_at: datetime


class ResultIn(BaseModel):
    result: StageResult


class PlanIn(BaseModel):
    planned_on: date


class CalendarEntry(BaseModel):
    olympiad_id: int
    olympiad_name: str
    subject_id: Optional[int] = None
    level: Optional[int] = None
    stage_id: int
    stage_name: str
    kind: StageKind
    # Полоса в календаре: от начала до конца этапа.
    window_start: date
    window_end: date
    # Однодневный этап — кружок целиком в цвет олимпиады и флажок.
    single_day: bool
    planned_on: Optional[date] = None


class CalendarOut(BaseModel):
    date_from: date
    date_to: date
    entries: List[CalendarEntry]


class DayOption(BaseModel):
    olympiad_id: int
    olympiad_name: str
    subject_id: Optional[int] = None
    stage_id: int
    stage_name: str
    kind: StageKind
    selected: bool
    # Этап уже запланирован на другой день — серый, с замком.
    planned_on_other_day: Optional[date] = None
    # Можно ли поставить галочку прямо сейчас.
    selectable: bool


class DayOut(BaseModel):
    """Всплывающее окно «В этот день я буду писать…»."""

    day: date
    limit: int
    selected_count: int
    past: bool
    options: List[DayOption]


class NewsItemOut(BaseModel):
    olympiad_id: int
    olympiad_name: str
    subject_id: Optional[int] = None
    level: Optional[int] = None
    stage_id: int
    stage_name: str
    message: str
    event_date: Optional[date] = None
    raw_date_range: Optional[str] = None
    result: Optional[StageResult] = None

    @classmethod
    def build(cls, item: NewsItem) -> "NewsItemOut":
        return cls(
            olympiad_id=item.olympiad_id,
            olympiad_name=item.olympiad_name,
            subject_id=item.subject_id,
            level=item.level,
            stage_id=item.stage_id,
            stage_name=item.stage_name,
            message=item.message,
            event_date=item.event_date,
            raw_date_range=item.raw_date_range,
            result=item.result,
        )


class NewsFeedOut(BaseModel):
    urgent: List[NewsItemOut]
    soon: List[NewsItemOut]
    later: List[NewsItemOut]
    awaiting_answer: List[NewsItemOut]
    finished: List[NewsItemOut]


class MySort(str, Enum):
    URGENCY = "urgency"
    LEVEL = "level"
    SUBJECT = "subject"


# ---------------------------------------------------------------------
# Вспомогательное
# ---------------------------------------------------------------------


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _violation(violation: RuleViolation) -> HTTPException:
    return _error(violation.status, violation.code, violation.message)


async def _lock_user(session: AsyncSession, user_id: int) -> None:
    """Сериализует изменения одного пользователя.

    Двойной тап по галочке отправляет два запроса почти одновременно; без
    блокировки оба прошли бы проверку лимита «три в день» и записали бы
    четвёртый план. Блокировка транзакционная и снимается при коммите.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:key AS BIGINT))"), {"key": user_id}
    )


async def _load_saved(
    session: AsyncSession, user_id: int, olympiad_id: Optional[int] = None
) -> List[Tuple[Olympiad, datetime]]:
    statement = (
        select(Olympiad, SavedOlympiad.added_at)
        .join(SavedOlympiad, SavedOlympiad.olympiad_id == Olympiad.id)
        .where(SavedOlympiad.user_id == user_id)
        .options(selectinload(Olympiad.stages), selectinload(Olympiad.subject))
    )
    if olympiad_id is not None:
        statement = statement.where(Olympiad.id == olympiad_id)
    rows = await session.execute(statement)
    return [(olympiad, added_at) for olympiad, added_at in rows.all()]


async def _results(
    session: AsyncSession, user_id: int, stage_ids: Iterable[int]
) -> Dict[int, StageResult]:
    ids = list(stage_ids)
    if not ids:
        return {}
    rows = await session.execute(
        select(StageProgress.stage_id, StageProgress.result).where(
            StageProgress.user_id == user_id, StageProgress.stage_id.in_(ids)
        )
    )
    return {stage_id: result for stage_id, result in rows.all()}


async def _plans(
    session: AsyncSession, user_id: int, stage_ids: Optional[Iterable[int]] = None
) -> Dict[int, date]:
    statement = select(StagePlan.stage_id, StagePlan.planned_on).where(
        StagePlan.user_id == user_id
    )
    if stage_ids is not None:
        ids = list(stage_ids)
        if not ids:
            return {}
        statement = statement.where(StagePlan.stage_id.in_(ids))
    rows = await session.execute(statement)
    return {stage_id: planned_on for stage_id, planned_on in rows.all()}


def _build_my_olympiad(
    olympiad: Olympiad,
    added_at: datetime,
    results: Dict[int, StageResult],
    plans: Dict[int, date],
    today: date,
) -> MyOlympiadOut:
    stages = list(olympiad.stages)
    locked = locked_stage_ids(stages, results)

    my_stages = [
        MyStageOut.build_personal(
            stage,
            today,
            result=results.get(stage.id),
            planned_on=plans.get(stage.id),
            locked=stage.id in locked,
        )
        for stage in stages
    ]
    by_id = {item.id: item for item in my_stages}
    next_stage = pick_next_stage([s for s in stages if s.id not in locked], today)

    return MyOlympiadOut(
        id=olympiad.id,
        name=olympiad.name,
        level=olympiad.level,
        levels=list(olympiad.levels or []),
        summary=olympiad.summary,
        subject_id=olympiad.subject_id,
        subject_name=olympiad.subject.name if olympiad.subject else None,
        subject=SubjectOut.build(olympiad.subject) if olympiad.subject else None,
        grades=olympiad.grades,
        grade_min=olympiad.grade_min,
        grade_max=olympiad.grade_max,
        partner_universities=list(olympiad.partner_universities or []),
        source_url=olympiad.source_url,
        official_url=olympiad.official_url,
        organizers=olympiad.organizers,
        added_at=added_at,
        eliminated=is_eliminated(results[s.id] for s in stages if s.id in results),
        next_stage=by_id.get(next_stage.id) if next_stage else None,
        stages=my_stages,
    )


async def _olympiad_state(
    session: AsyncSession, user_id: int, olympiad_id: int, today: date
) -> MyOlympiadOut:
    rows = await _load_saved(session, user_id, olympiad_id)
    if not rows:
        raise _error(404, "not_saved", "Олимпиады нет в «Моих олимпиадах»")
    olympiad, added_at = rows[0]
    stage_ids = [s.id for s in olympiad.stages]
    return _build_my_olympiad(
        olympiad,
        added_at,
        await _results(session, user_id, stage_ids),
        await _plans(session, user_id, stage_ids),
        today,
    )


class _StageContext:
    """Всё, что нужно правилам для решения по одному этапу."""

    def __init__(
        self,
        stage: Stage,
        olympiad: Olympiad,
        saved: bool,
        results: Dict[int, StageResult],
    ) -> None:
        self.stage = stage
        self.olympiad = olympiad
        self.saved = saved
        self.results = results
        self.locked_ids = locked_stage_ids(olympiad.stages, results)

    @property
    def locked(self) -> bool:
        return self.stage.id in self.locked_ids


async def _stage_context(session: AsyncSession, user_id: int, stage_id: int) -> _StageContext:
    olympiad_id = await session.scalar(select(Stage.olympiad_id).where(Stage.id == stage_id))
    if olympiad_id is None:
        raise _error(404, "not_found", "Этап не найден")

    olympiad = await session.scalar(
        select(Olympiad)
        .where(Olympiad.id == olympiad_id)
        .options(selectinload(Olympiad.stages), selectinload(Olympiad.subject))
    )
    stage = next(s for s in olympiad.stages if s.id == stage_id)
    saved = await session.get(SavedOlympiad, (user_id, olympiad.id)) is not None
    results = await _results(session, user_id, [s.id for s in olympiad.stages])
    return _StageContext(stage, olympiad, saved, results)


# ---------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------


def _settings_out(row: Optional[UserSettings]) -> SettingsOut:
    if row is None:
        return SettingsOut()
    return SettingsOut(
        grade=row.grade,
        notifications_enabled=row.notifications_enabled,
        colorblind_mode=row.colorblind_mode,
    )


@router.get("/settings", response_model=SettingsOut, summary="Настройки пользователя")
async def read_settings(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SettingsOut:
    # Запись не создаётся при чтении: значения по умолчанию и так известны.
    return _settings_out(await session.get(UserSettings, user.id))


@router.patch("/settings", response_model=SettingsOut, summary="Изменить настройки")
async def update_settings(
    body: SettingsPatch,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SettingsOut:
    values: Dict[str, object] = {}
    for name in body.model_fields_set:
        value = getattr(body, name)
        if name != "grade" and value is None:
            # null для переключателей бессмыслен — просто не трогаем их.
            continue
        values[name] = value

    if values:
        statement = (
            pg_insert(UserSettings)
            .values(user_id=user.id, **values)
            .on_conflict_do_update(
                index_elements=[UserSettings.user_id],
                set_={**values, "updated_at": func.now()},
            )
        )
        await session.execute(statement)
        await session.commit()

    return _settings_out(await session.get(UserSettings, user.id, populate_existing=True))


# ---------------------------------------------------------------------
# Мои олимпиады
# ---------------------------------------------------------------------


def _sort_key(sort: MySort):
    def urgency(item: MyOlympiadOut):
        stage = item.next_stage
        if stage is not None and stage.start_precision == "day" and stage.starts_on:
            return (0, stage.starts_on)
        return (1, date.max)

    def by_level(item: MyOlympiadOut):
        return (item.level is None, item.level or 0)

    def by_subject(item: MyOlympiadOut):
        return (item.subject_name is None, item.subject_name or "")

    inner = {MySort.URGENCY: urgency, MySort.LEVEL: by_level, MySort.SUBJECT: by_subject}[sort]
    # Олимпиада, закончившаяся «не прошёл», всегда внизу списка.
    return lambda item: (item.eliminated, inner(item), item.name)


@router.get("/olympiads", response_model=MyOlympiadList, summary="Мои олимпиады")
async def list_my_olympiads(
    sort: MySort = Query(default=MySort.URGENCY),
    subject_id: List[int] = Query(default=[], description="фильтр, можно несколько"),
    q: Optional[str] = Query(default=None, description="поиск по названию и предмету"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MyOlympiadList:
    today = app_today()
    rows = await _load_saved(session, user.id)
    stage_ids = [s.id for olympiad, _ in rows for s in olympiad.stages]
    results = await _results(session, user.id, stage_ids)
    plans = await _plans(session, user.id, stage_ids)

    items = [_build_my_olympiad(o, added, results, plans, today) for o, added in rows]
    if subject_id:
        wanted = set(subject_id)
        items = [item for item in items if item.subject_id in wanted]
    if q:
        # Список сохранённого невелик, отдельный запрос в базу не нужен.
        needle = q.strip().lower()
        items = [
            item
            for item in items
            if needle in item.name.lower()
            or needle in (item.subject_name or "").lower()
        ]
    items.sort(key=_sort_key(sort))

    return MyOlympiadList(items=items, total=len(items))


@router.get(
    "/olympiads/{olympiad_id}",
    response_model=MyOlympiadOut,
    summary="Олимпиада из моих, с прогрессом и планами",
)
async def read_my_olympiad(
    olympiad_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MyOlympiadOut:
    return await _olympiad_state(session, user.id, olympiad_id, app_today())


@router.post(
    "/olympiads/{olympiad_id}",
    response_model=SaveOut,
    summary="Буду писать — добавить в мои",
    responses={200: {"description": "Уже была добавлена"}, 201: {"description": "Добавлена"}},
)
async def save_olympiad(
    olympiad_id: int,
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SaveOut:
    if await session.get(Olympiad, olympiad_id) is None:
        raise _error(404, "not_found", "Олимпиада не найдена")

    inserted = await session.execute(
        pg_insert(SavedOlympiad)
        .values(user_id=user.id, olympiad_id=olympiad_id)
        .on_conflict_do_nothing()
        .returning(SavedOlympiad.added_at)
    )
    added_at = inserted.scalar_one_or_none()
    created = added_at is not None
    if not created:
        added_at = await session.scalar(
            select(SavedOlympiad.added_at).where(
                SavedOlympiad.user_id == user.id, SavedOlympiad.olympiad_id == olympiad_id
            )
        )
    await session.commit()

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return SaveOut(olympiad_id=olympiad_id, saved=True, added_at=added_at)


@router.delete(
    "/olympiads/{olympiad_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить из моих олимпиад",
)
async def remove_olympiad(
    olympiad_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _lock_user(session, user.id)
    stage_ids = select(Stage.id).where(Stage.olympiad_id == olympiad_id)

    # Вместе с олимпиадой уходят её планы и прогресс: иначе они продолжили
    # бы занимать слоты в календаре и всплывать в новостях.
    await session.execute(
        delete(StagePlan).where(StagePlan.user_id == user.id, StagePlan.stage_id.in_(stage_ids))
    )
    await session.execute(
        delete(StageProgress).where(
            StageProgress.user_id == user.id, StageProgress.stage_id.in_(stage_ids)
        )
    )
    await session.execute(
        delete(SavedOlympiad).where(
            SavedOlympiad.user_id == user.id, SavedOlympiad.olympiad_id == olympiad_id
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------
# Прогресс: прошёл / не прошёл
# ---------------------------------------------------------------------


@router.put(
    "/stages/{stage_id}/result",
    response_model=MyOlympiadOut,
    summary="Отметить: прошёл или не прошёл",
)
async def set_stage_result(
    stage_id: int,
    body: ResultIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MyOlympiadOut:
    today = app_today()
    await _lock_user(session, user.id)
    ctx = await _stage_context(session, user.id, stage_id)

    try:
        check_can_answer(ctx.stage, saved=ctx.saved, locked=ctx.locked, today=today)
    except RuleViolation as violation:
        raise _violation(violation) from violation

    await session.execute(
        pg_insert(StageProgress)
        .values(user_id=user.id, stage_id=stage_id, result=body.result)
        .on_conflict_do_update(
            index_elements=[StageProgress.user_id, StageProgress.stage_id],
            set_={"result": body.result, "answered_at": func.now()},
        )
    )

    if body.result is StageResult.FAILED:
        # «Не прошёл» — конец олимпиады: всё, что было после, снимается
        # с календаря и из прогресса. Отмена ответа это не восстановит.
        later = [s.id for s in ctx.olympiad.stages if s.position > ctx.stage.position]
        if later:
            await session.execute(
                delete(StagePlan).where(StagePlan.user_id == user.id, StagePlan.stage_id.in_(later))
            )
            await session.execute(
                delete(StageProgress).where(
                    StageProgress.user_id == user.id, StageProgress.stage_id.in_(later)
                )
            )

    await session.commit()
    return await _olympiad_state(session, user.id, ctx.olympiad.id, today)


@router.delete(
    "/stages/{stage_id}/result",
    response_model=MyOlympiadOut,
    summary="Отменить ответ",
)
async def clear_stage_result(
    stage_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MyOlympiadOut:
    today = app_today()
    await _lock_user(session, user.id)
    ctx = await _stage_context(session, user.id, stage_id)
    if not ctx.saved:
        raise _error(409, "not_saved", "Сначала добавьте олимпиаду в «Мои олимпиады»")

    await session.execute(
        delete(StageProgress).where(
            StageProgress.user_id == user.id, StageProgress.stage_id == stage_id
        )
    )
    await session.commit()
    return await _olympiad_state(session, user.id, ctx.olympiad.id, today)


# ---------------------------------------------------------------------
# Календарь
# ---------------------------------------------------------------------


@router.put(
    "/stages/{stage_id}/plan",
    response_model=MyOlympiadOut,
    summary="Запланировать этап на день",
)
async def plan_stage(
    stage_id: int,
    body: PlanIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MyOlympiadOut:
    today = app_today()
    await _lock_user(session, user.id)
    ctx = await _stage_context(session, user.id, stage_id)

    existing = await session.get(StagePlan, (user.id, stage_id))
    planned_that_day = await session.scalar(
        select(func.count())
        .select_from(StagePlan)
        .where(
            StagePlan.user_id == user.id,
            StagePlan.planned_on == body.planned_on,
            StagePlan.stage_id != stage_id,
        )
    )

    try:
        check_can_plan(
            ctx.stage,
            body.planned_on,
            saved=ctx.saved,
            locked=ctx.locked,
            today=today,
            existing_plan=existing.planned_on if existing else None,
            planned_that_day=planned_that_day or 0,
        )
    except RuleViolation as violation:
        raise _violation(violation) from violation

    if existing is None:
        session.add(StagePlan(user_id=user.id, stage_id=stage_id, planned_on=body.planned_on))
    await session.commit()
    return await _olympiad_state(session, user.id, ctx.olympiad.id, today)


@router.delete(
    "/stages/{stage_id}/plan",
    response_model=MyOlympiadOut,
    summary="Снять этап с календаря",
)
async def unplan_stage(
    stage_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MyOlympiadOut:
    today = app_today()
    await _lock_user(session, user.id)
    ctx = await _stage_context(session, user.id, stage_id)
    if not ctx.saved:
        raise _error(409, "not_saved", "Сначала добавьте олимпиаду в «Мои олимпиады»")

    await session.execute(
        delete(StagePlan).where(StagePlan.user_id == user.id, StagePlan.stage_id == stage_id)
    )
    await session.commit()
    return await _olympiad_state(session, user.id, ctx.olympiad.id, today)


def _month_bounds(day: date) -> Tuple[date, date]:
    last = pycalendar.monthrange(day.year, day.month)[1]
    return day.replace(day=1), day.replace(day=last)


def _open_stages(
    rows: Sequence[Tuple[Olympiad, datetime]], results: Dict[int, StageResult]
) -> Iterable[Tuple[Olympiad, Stage, Tuple[date, date]]]:
    """Этапы сохранённых олимпиад, которые можно показать в календаре."""
    for olympiad, _ in rows:
        locked = locked_stage_ids(olympiad.stages, results)
        for stage in olympiad.stages:
            if stage.id in locked:
                continue
            window = plan_window(stage)
            if window is not None:
                yield olympiad, stage, window


@router.get("/calendar", response_model=CalendarOut, summary="Календарь за период")
async def read_calendar(
    date_from: Optional[date] = Query(default=None, description="по умолчанию — начало месяца"),
    date_to: Optional[date] = Query(default=None, description="по умолчанию — конец месяца"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CalendarOut:
    month_start, month_end = _month_bounds(app_today())
    start = date_from or month_start
    end = date_to or month_end

    if end < start:
        raise _error(422, "bad_range", "date_to раньше date_from")
    if (end - start).days > MAX_CALENDAR_SPAN_DAYS:
        raise _error(422, "bad_range", f"Период не может быть длиннее {MAX_CALENDAR_SPAN_DAYS} дней")

    rows = await _load_saved(session, user.id)
    stage_ids = [s.id for olympiad, _ in rows for s in olympiad.stages]
    results = await _results(session, user.id, stage_ids)
    plans = await _plans(session, user.id, stage_ids)

    entries = [
        CalendarEntry(
            olympiad_id=olympiad.id,
            olympiad_name=olympiad.name,
            subject_id=olympiad.subject_id,
            level=olympiad.level,
            stage_id=stage.id,
            stage_name=stage.name,
            kind=stage.kind,
            window_start=window[0],
            window_end=window[1],
            single_day=window[0] == window[1],
            planned_on=plans.get(stage.id),
        )
        for olympiad, stage, window in _open_stages(rows, results)
        if window[1] >= start and window[0] <= end
    ]
    entries.sort(key=lambda e: (e.window_start, e.olympiad_name))
    return CalendarOut(date_from=start, date_to=end, entries=entries)


@router.get(
    "/calendar/{day}",
    response_model=DayOut,
    summary="В этот день я буду писать…",
)
async def read_calendar_day(
    day: date,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DayOut:
    today = app_today()
    rows = await _load_saved(session, user.id)
    stage_ids = [s.id for olympiad, _ in rows for s in olympiad.stages]
    results = await _results(session, user.id, stage_ids)
    plans = await _plans(session, user.id, stage_ids)

    selected_count = sum(1 for planned in plans.values() if planned == day)
    past = day < today

    options: List[DayOption] = []
    for olympiad, stage, (start, end) in _open_stages(rows, results):
        if not (start <= day <= end):
            continue
        planned = plans.get(stage.id)
        selected = planned == day
        other_day = planned if planned is not None and not selected else None
        options.append(
            DayOption(
                olympiad_id=olympiad.id,
                olympiad_name=olympiad.name,
                subject_id=olympiad.subject_id,
                stage_id=stage.id,
                stage_name=stage.name,
                kind=stage.kind,
                selected=selected,
                planned_on_other_day=other_day,
                selectable=(
                    not past
                    and other_day is None
                    and (selected or selected_count < DAILY_PLAN_LIMIT)
                ),
            )
        )

    # Выбранные сверху, затем доступные, затем заблокированные.
    options.sort(key=lambda o: (not o.selected, not o.selectable, o.olympiad_name))
    return DayOut(
        day=day,
        limit=DAILY_PLAN_LIMIT,
        selected_count=selected_count,
        past=past,
        options=options,
    )


# ---------------------------------------------------------------------
# Новости
# ---------------------------------------------------------------------


@router.get("/news", response_model=NewsFeedOut, summary="Новости по моим олимпиадам")
async def read_news(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> NewsFeedOut:
    today = app_today()
    rows = await _load_saved(session, user.id)
    stage_ids = [s.id for olympiad, _ in rows for s in olympiad.stages]
    results = await _results(session, user.id, stage_ids)

    entries = []
    for olympiad, _ in rows:
        locked = locked_stage_ids(olympiad.stages, results)
        for stage in olympiad.stages:
            entries.append((olympiad, stage, results.get(stage.id), stage.id in locked))

    feed = build_feed(entries, today=today)
    return NewsFeedOut(
        urgent=[NewsItemOut.build(i) for i in feed.urgent],
        soon=[NewsItemOut.build(i) for i in feed.soon],
        later=[NewsItemOut.build(i) for i in feed.later],
        awaiting_answer=[NewsItemOut.build(i) for i in feed.awaiting_answer],
        finished=[NewsItemOut.build(i) for i in feed.finished],
    )
