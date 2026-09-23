"""Эндпоинты каталога олимпиад.

Отдают данные для вкладки «Поиск» и карточек. Требуют ту же
аутентификацию по подписи данных запуска, что и остальной API.

Ключевая договорённость с фронтендом: у каждого этапа приходят поля
``*_precision`` и ``days_until_start``. Если ``days_until_start`` равен
``null``, таймер показывать нельзя — вместо него выводится
``raw_date_range`` как есть («март 2027»).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..catalog.models import Olympiad, Stage, StageKind, Subject
from ..catalog.presentation import (
    StageStatus,
    days_until_start,
    is_plannable,
    pick_next_stage,
    split_organizers,
    stage_status,
)
from ..clock import today as app_today
from ..db.models import User
from ..personal.models import SavedOlympiad
from ..db.session import get_session
from ..security.deps import get_current_user

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


class SubjectOut(BaseModel):
    """Предмет: цвет для кружка и короткий код для режима дальтоников."""

    id: int
    name: str
    color: Optional[str] = None
    short_code: Optional[str] = None

    @classmethod
    def build(cls, subject: Subject) -> "SubjectOut":
        return cls(
            id=subject.id,
            name=subject.name,
            color=subject.color,
            short_code=subject.short_code,
        )


class SortOrder(str, Enum):
    """Варианты сортировки из механики приложения."""

    URGENCY = "urgency"
    NAME = "name"
    LEVEL = "level"


class StageOut(BaseModel):
    id: int
    name: str
    kind: StageKind

    starts_on: Optional[date] = None
    ends_on: Optional[date] = None
    # "day" — известен точный день, "month" — только месяц и год.
    start_precision: Optional[str] = None
    end_precision: Optional[str] = None

    # Исходная строка источника. Показывать, когда точности не хватает.
    raw_date_range: Optional[str] = None

    status: StageStatus
    # null, если точного дня нет — таймер в этом случае недопустим.
    days_until_start: Optional[int] = None
    # false, если этап нельзя поставить в календарь по дням.
    plannable: bool

    source_url: Optional[str] = None

    @classmethod
    def build(cls, stage: Stage, today: date) -> "StageOut":
        return cls(
            id=stage.id,
            name=stage.name,
            kind=stage.kind,
            starts_on=stage.starts_on,
            ends_on=stage.ends_on,
            start_precision=stage.start_precision.value if stage.start_precision else None,
            end_precision=stage.end_precision.value if stage.end_precision else None,
            raw_date_range=stage.raw_date_range,
            status=stage_status(stage, today),
            days_until_start=days_until_start(stage, today),
            plannable=is_plannable(stage),
            source_url=stage.source_url,
        )


class OlympiadListItem(BaseModel):
    id: int
    name: str
    # Лучший уровень по перечню РСОШ — для сортировки «от I к III».
    level: Optional[int] = None
    # Все уровни по этому предмету: иногда их два, тогда показывают «II–III ур.».
    levels: List[int] = Field(default_factory=list)
    summary: Optional[str] = None
    subject_id: Optional[int] = None
    subject: Optional[SubjectOut] = None
    # Классы участников строкой источника: «7-11 классы» или null.
    grades: Optional[str] = None
    # Та же строка числами — для подсветки «подходит вашему классу».
    grade_min: Optional[int] = None
    grade_max: Optional[int] = None
    partner_universities: List[str] = Field(default_factory=list)
    # Ссылки на страницу источника есть не у всех записей: файл команды
    # отдаёт только официальный сайт олимпиады.
    source_url: Optional[str] = None
    # Ближайший идущий или предстоящий этап — для подписи на карточке.
    next_stage: Optional[StageOut] = None
    # Добавлена ли в «Мои олимпиады»: кнопка «Буду писать» / «✓ Добавлено».
    saved: bool = False


class OlympiadDetail(OlympiadListItem):
    official_url: Optional[str] = None
    # Организаторы одной строкой, как их отдаёт источник.
    organizers: Optional[str] = None
    # Та же строка, разобранная на отдельные названия: до трёх, как в
    # механике. Разбор приблизительный — см. split_organizers.
    organizers_list: List[str] = Field(default_factory=list)
    stages: List[StageOut] = Field(default_factory=list)
    # Откуда запись и когда её последний раз подтверждали в источнике.
    source: str
    source_checked_at: Optional[datetime] = None


class OlympiadPage(BaseModel):
    items: List[OlympiadListItem]
    total: int
    limit: int
    offset: int


async def _saved_ids(session: AsyncSession, user_id: int, olympiad_ids: List[int]) -> set:
    """Какие из олимпиад пользователь уже добавил к себе."""
    if not olympiad_ids:
        return set()
    rows = await session.scalars(
        select(SavedOlympiad.olympiad_id).where(
            SavedOlympiad.user_id == user_id,
            SavedOlympiad.olympiad_id.in_(olympiad_ids),
        )
    )
    return set(rows)


def _to_list_item(olympiad: Olympiad, today: date, saved: bool = False) -> OlympiadListItem:
    next_stage = pick_next_stage(olympiad.stages, today)
    return OlympiadListItem(
        id=olympiad.id,
        name=olympiad.name,
        level=olympiad.level,
        summary=olympiad.summary,
        levels=list(olympiad.levels or []),
        subject_id=olympiad.subject_id,
        subject=SubjectOut.build(olympiad.subject) if olympiad.subject else None,
        grades=olympiad.grades,
        grade_min=olympiad.grade_min,
        grade_max=olympiad.grade_max,
        partner_universities=list(olympiad.partner_universities or []),
        source_url=olympiad.source_url,
        next_stage=StageOut.build(next_stage, today) if next_stage else None,
        saved=saved,
    )


@router.get("/olympiads", response_model=OlympiadPage, summary="Список олимпиад")
async def list_olympiads(
    q: Optional[str] = Query(default=None, description="поиск по названию и предмету"),
    subject_id: Optional[int] = Query(default=None),
    level: Optional[int] = Query(default=None, ge=1, le=3),
    grade: Optional[int] = Query(
        default=None, ge=1, le=11, description="оставить подходящие этому классу"
    ),
    sort: SortOrder = Query(default=SortOrder.URGENCY),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> OlympiadPage:
    today = app_today()

    filters = []
    if q:
        # Механика ищет «по названию или предмету» — второе через
        # подзапрос, чтобы не тащить join в основную выборку.
        pattern = f"%{q}%"
        by_subject = select(Subject.id).where(Subject.name.ilike(pattern)).scalar_subquery()
        filters.append(
            or_(Olympiad.name.ilike(pattern), Olympiad.subject_id.in_(by_subject))
        )
    if subject_id is not None:
        filters.append(Olympiad.subject_id == subject_id)
    if level is not None:
        filters.append(Olympiad.level == level)
    if grade is not None:
        # Записи без данных о классах не прячем: неизвестно — не значит
        # «не подходит», и скрывать их было бы враньём.
        filters.append(
            or_(Olympiad.grade_min.is_(None), Olympiad.grade_min <= grade)
        )
        filters.append(
            or_(Olympiad.grade_max.is_(None), Olympiad.grade_max >= grade)
        )

    total = await session.scalar(
        select(func.count()).select_from(Olympiad).where(*filters)
    )

    statement = (
        select(Olympiad)
        .where(*filters)
        .options(selectinload(Olympiad.stages), selectinload(Olympiad.subject))
    )

    if sort is SortOrder.NAME:
        statement = statement.order_by(Olympiad.name)
    elif sort is SortOrder.LEVEL:
        # Олимпиады без уровня уходят в конец, а не выдают себя за первый.
        statement = statement.order_by(
            Olympiad.level.is_(None), Olympiad.level, Olympiad.name
        )
    else:
        # По срочности: ближайшая предстоящая дата начала среди этапов,
        # у которых известен точный день. Без таких этапов — в конец.
        nearest = (
            select(func.min(Stage.starts_on))
            .where(
                Stage.olympiad_id == Olympiad.id,
                Stage.starts_on >= today,
                Stage.start_precision == "day",
            )
            .scalar_subquery()
        )
        statement = statement.order_by(nearest.is_(None), nearest, Olympiad.name)

    olympiads = list(await session.scalars(statement.limit(limit).offset(offset)))
    saved = await _saved_ids(session, user.id, [o.id for o in olympiads])
    items = [_to_list_item(o, today, saved=o.id in saved) for o in olympiads]

    return OlympiadPage(items=items, total=total or 0, limit=limit, offset=offset)


@router.get(
    "/olympiads/{olympiad_id}",
    response_model=OlympiadDetail,
    summary="Олимпиада со всеми этапами",
)
async def get_olympiad(
    olympiad_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> OlympiadDetail:
    olympiad = await session.scalar(
        select(Olympiad)
        .where(Olympiad.id == olympiad_id)
        .options(selectinload(Olympiad.stages), selectinload(Olympiad.subject))
    )
    if olympiad is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Олимпиада не найдена"
        )

    today = app_today()
    saved = await _saved_ids(session, user.id, [olympiad.id])
    base = _to_list_item(olympiad, today, saved=olympiad.id in saved)

    return OlympiadDetail(
        **base.model_dump(),
        official_url=olympiad.official_url,
        organizers=olympiad.organizers,
        organizers_list=split_organizers(olympiad.organizers),
        source=olympiad.source,
        source_checked_at=olympiad.source_checked_at,
        stages=[StageOut.build(stage, today) for stage in olympiad.stages],
    )


@router.get("/subjects", response_model=List[SubjectOut], summary="Справочник предметов")
async def list_subjects(
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> List[SubjectOut]:
    """Предметы с цветами и короткими кодами.

    Отдаётся сервером, чтобы цвета карточек и подписи в режиме для
    дальтоников не расходились между фронтендом и базой.
    """
    subjects = await session.scalars(select(Subject).order_by(Subject.name))
    return [SubjectOut.build(subject) for subject in subjects]
