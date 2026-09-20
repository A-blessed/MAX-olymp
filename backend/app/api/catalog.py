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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..catalog.models import Olympiad, Stage, StageKind
from ..catalog.presentation import (
    StageStatus,
    days_until_start,
    is_plannable,
    stage_status,
)
from ..db.models import User
from ..db.session import get_session
from ..security.deps import get_current_user

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


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
    level: Optional[int] = None
    summary: Optional[str] = None
    subject_id: Optional[int] = None
    partner_universities: List[str] = Field(default_factory=list)
    source_url: str
    # Ближайший идущий или предстоящий этап — для подписи на карточке.
    next_stage: Optional[StageOut] = None


class OlympiadDetail(OlympiadListItem):
    official_url: Optional[str] = None
    stages: List[StageOut] = Field(default_factory=list)
    # Откуда запись и когда её последний раз подтверждали в источнике.
    source: str
    source_checked_at: Optional[datetime] = None


class OlympiadPage(BaseModel):
    items: List[OlympiadListItem]
    total: int
    limit: int
    offset: int


def _pick_next_stage(stages: List[Stage], today: date) -> Optional[Stage]:
    """Ближайший идущий или предстоящий этап.

    Этапы без точного дня участвуют, но уступают точным: подпись
    «до этапа N дней» полезнее, чем «март 2027».
    """
    active = [s for s in stages if stage_status(s, today) is StageStatus.ACTIVE]
    if active:
        return active[0]

    upcoming = [
        s
        for s in stages
        if stage_status(s, today) is StageStatus.UPCOMING and s.starts_on is not None
    ]
    if not upcoming:
        return None
    upcoming.sort(key=lambda s: (not is_plannable(s), s.starts_on))
    return upcoming[0]


def _to_list_item(olympiad: Olympiad, today: date) -> OlympiadListItem:
    next_stage = _pick_next_stage(list(olympiad.stages), today)
    return OlympiadListItem(
        id=olympiad.id,
        name=olympiad.name,
        level=olympiad.level,
        summary=olympiad.summary,
        subject_id=olympiad.subject_id,
        partner_universities=list(olympiad.partner_universities or []),
        source_url=olympiad.source_url,
        next_stage=StageOut.build(next_stage, today) if next_stage else None,
    )


@router.get("/olympiads", response_model=OlympiadPage, summary="Список олимпиад")
async def list_olympiads(
    q: Optional[str] = Query(default=None, description="поиск по названию"),
    subject_id: Optional[int] = Query(default=None),
    level: Optional[int] = Query(default=None, ge=1, le=3),
    sort: SortOrder = Query(default=SortOrder.URGENCY),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> OlympiadPage:
    today = date.today()

    filters = []
    if q:
        filters.append(Olympiad.name.ilike(f"%{q}%"))
    if subject_id is not None:
        filters.append(Olympiad.subject_id == subject_id)
    if level is not None:
        filters.append(Olympiad.level == level)

    total = await session.scalar(
        select(func.count()).select_from(Olympiad).where(*filters)
    )

    statement = select(Olympiad).where(*filters).options(selectinload(Olympiad.stages))

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

    result = await session.scalars(statement.limit(limit).offset(offset))
    items = [_to_list_item(olympiad, today) for olympiad in result]

    return OlympiadPage(items=items, total=total or 0, limit=limit, offset=offset)


@router.get(
    "/olympiads/{olympiad_id}",
    response_model=OlympiadDetail,
    summary="Олимпиада со всеми этапами",
)
async def get_olympiad(
    olympiad_id: int,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> OlympiadDetail:
    olympiad = await session.scalar(
        select(Olympiad)
        .where(Olympiad.id == olympiad_id)
        .options(selectinload(Olympiad.stages))
    )
    if olympiad is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Олимпиада не найдена"
        )

    today = date.today()
    base = _to_list_item(olympiad, today)

    return OlympiadDetail(
        **base.model_dump(),
        official_url=olympiad.official_url,
        source=olympiad.source,
        source_checked_at=olympiad.source_checked_at,
        stages=[StageOut.build(stage, today) for stage in olympiad.stages],
    )
