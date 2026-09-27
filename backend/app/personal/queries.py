"""Выборки по пользователю, общие для API и бота.

Экраны «Мои олимпиады», «Календарь», «Новости» и утренние напоминания
отвечают на один и тот же вопрос — что у этого пользователя и в каком
состоянии. Пока выборки жили в слое API, боту пришлось бы либо тянуть их
оттуда, либо писать свои; во втором случае приложение и бот рано или
поздно разошлись бы в том, какие этапы считать заблокированными.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..catalog.models import Olympiad
from .models import SavedOlympiad, StagePlan, StageProgress, StageResult


async def load_saved(
    session: AsyncSession, user_id: int, olympiad_id: Optional[int] = None
) -> List[Tuple[Olympiad, datetime]]:
    """Сохранённые олимпиады пользователя вместе с этапами и предметом."""
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


async def load_results(
    session: AsyncSession, user_id: int, stage_ids: Iterable[int]
) -> Dict[int, StageResult]:
    """Ответы «прошёл / не прошёл» по этапам."""
    ids = list(stage_ids)
    if not ids:
        return {}
    rows = await session.execute(
        select(StageProgress.stage_id, StageProgress.result).where(
            StageProgress.user_id == user_id, StageProgress.stage_id.in_(ids)
        )
    )
    return {stage_id: result for stage_id, result in rows.all()}


async def load_plans(
    session: AsyncSession, user_id: int, stage_ids: Optional[Iterable[int]] = None
) -> Dict[int, date]:
    """Дни, на которые пользователь запланировал этапы."""
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
