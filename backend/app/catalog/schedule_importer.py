"""Импорт расписания этапов, снятого с olimpiada.ru.

Парсер отдаёт файл, в котором этапы сгруппированы по ``activity_id`` —
идентификатору олимпиады на olimpiada.ru. В базе его нет: импорт по
предметам заводит олимпиады под ключом ``id`` из файла каталога. Связь
восстанавливается по этому же файлу, где рядом лежат оба идентификатора,
поэтому каталог подменять не требуется — он нужен только как таблица
соответствия.

Точность дат парсер описывает своим словарём, и описывает им не точность
отдельной даты, а форму интервала:

    ``exact``   — один день;
    ``range``   — с какого по какое;
    ``until``   — известен только дедлайн, начала нет;
    ``unknown`` — дат нет вовсе.

В модели точность хранится у каждой даты отдельно, и все четыре случая
выражаются через неё без новых полей: значение несёт то, какие из дат
заполнены. Обратное преобразование, для календаря, делает
``presentation.date_precision`` — держать его рядом с чтением, а не с
записью, надёжнее: вычисленное значение не может разойтись с данными.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .dates import Precision
from .importer import classify_stage
from .models import Olympiad, Stage
from .subject_importer import SOURCE_NAME

logger = logging.getLogger(__name__)

PRECISION_EXACT = "exact"
PRECISION_RANGE = "range"
PRECISION_UNTIL = "until"
PRECISION_UNKNOWN = "unknown"


def parse_iso(value: Any) -> Optional[date]:
    """Дата из строки ISO. Парсер отдаёт либо её, либо ``null``."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


StageDates = Tuple[Optional[date], Optional[Precision], Optional[date], Optional[Precision]]


def stage_dates(payload: Dict[str, Any]) -> StageDates:
    """Даты этапа в том виде, в каком их хранит модель.

    Возвращает четвёрку ``(начало, точность, конец, точность)``. Пустые
    значения намеренны: у ``until`` начала не существует, и подставлять
    вместо него дедлайн нельзя — календарь рисует такой этап иначе, а
    напоминание «за день до начала» стало бы враньём.
    """
    start = parse_iso(payload.get("start_stage"))
    end = parse_iso(payload.get("end_stage"))
    precision = (payload.get("date_precision") or "").strip().lower()

    if precision == PRECISION_UNTIL:
        if end is None:
            return None, None, None, None
        return None, None, end, Precision.DAY

    if precision == PRECISION_RANGE and start is not None and end is not None and end > start:
        return start, Precision.DAY, end, Precision.DAY

    if precision in (PRECISION_EXACT, PRECISION_RANGE) and start is not None:
        # У ``exact`` парсер кладёт один и тот же день в оба поля, а
        # ``range`` иногда схлопывается в один день. И то и другое —
        # точка, и хранить её надо как точку: иначе календарь нарисует
        # полосу длиной в сутки вместо кружка.
        return start, Precision.DAY, None, None

    return None, None, None, None


def stage_external_key(name: str, taken: Set[str]) -> str:
    """Устойчивый ключ этапа внутри олимпиады.

    Ссылки на отдельный этап у парсера нет, поэтому ключом служит
    нормализованное название: оно переживает повторный импорт. Порядковый
    номер не годится — стоит источнику переставить этапы местами, и
    прогресс пользователя («прошёл / не прошёл») перескочит на чужой этап.
    """
    normalized = re.sub(r"\s+", " ", (name or "")).strip().lower()
    key = (normalized or "stage")[:255]
    if key not in taken:
        return key

    # Одинаковые названия у одной олимпиады встречаются — разводим суффиксом.
    for index in range(2, 100):
        candidate = f"{key[:250]}-{index}"
        if candidate not in taken:
            return candidate
    return key


def build_activity_index(catalog: Dict[str, Any]) -> Dict[int, List[str]]:
    """Соответствие ``activity_id`` с olimpiada.ru → ``external_id`` в базе.

    Значение — список, а не одна строка. Один и тот же ``activity_id``
    встречается у разных олимпиад: в каталоге такие пары есть, и хранить
    только последнюю значило бы молча лишить вторую расписания. Пусть
    лучше обе получат одинаковые этапы — это видно и поправимо, а тихая
    пропажа — нет.

    Повтор одного ``external_id`` под разными предметами — дело обычное и
    к списку ничего не добавляет: одна олимпиада, несколько предметов.
    """
    index: Dict[int, List[str]] = {}
    for subject in catalog.get("subjects") or []:
        for olympiad in subject.get("olympiads") or []:
            external_id = str(olympiad.get("id") or "").strip()
            raw_activity = olympiad.get("activity_id")
            if not external_id or raw_activity is None:
                continue
            try:
                activity_id = int(raw_activity)
            except (TypeError, ValueError):
                continue
            known = index.setdefault(activity_id, [])
            if external_id not in known:
                known.append(external_id)
    return index


@dataclass
class ScheduleImportStats:
    """Что именно сделал импорт — попадает в лог и в вывод скрипта."""

    olympiads_matched: int = 0
    stages_created: int = 0
    stages_updated: int = 0
    stages_removed: int = 0
    without_schedule: int = 0
    unmatched: List[str] = field(default_factory=list)
    skipped_stages: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "олимпиад с расписанием": self.olympiads_matched,
            "этапов добавлено": self.stages_created,
            "этапов обновлено": self.stages_updated,
            "этапов удалено": self.stages_removed,
            "без расписания в источнике": self.without_schedule,
            "не нашлось в базе": len(self.unmatched),
            "этапов пропущено": len(self.skipped_stages),
        }


async def import_schedules(
    session: AsyncSession,
    schedule: Dict[str, Any],
    catalog: Dict[str, Any],
) -> ScheduleImportStats:
    """Записывает расписание в каталог. Повторный запуск безопасен."""
    stats = ScheduleImportStats()
    index = build_activity_index(catalog)
    checked_at = datetime.now(timezone.utc)

    for raw_activity_id, entry in (schedule.get("schedules") or {}).items():
        payloads = entry.get("stages") or []
        if not payloads:
            # Страница без расписания — обычное дело: у большинства
            # олимпиад его на сайте просто нет. Существующие этапы при
            # этом не трогаем: пустой разбор чаще означает, что источник
            # поменял вёрстку, чем что этапы отменили.
            stats.without_schedule += 1
            continue

        try:
            activity_id = int(raw_activity_id)
        except (TypeError, ValueError):
            stats.unmatched.append(str(raw_activity_id))
            continue

        external_ids = index.get(activity_id)
        if not external_ids:
            stats.unmatched.append(f"activity_id={activity_id}: нет в файле каталога")
            continue

        if len(external_ids) > 1:
            logger.warning(
                "activity_id=%s указывает на разные олимпиады (%s) — расписание "
                "получат все. Похоже на ошибку в каталоге.",
                activity_id,
                ", ".join(external_ids),
            )

        # Одна олимпиада заводится по каждому своему предмету отдельной
        # строкой — ключ уникальности включает предмет. Расписание нужно
        # каждой из них.
        olympiads = list(
            await session.scalars(
                select(Olympiad).where(
                    Olympiad.source == SOURCE_NAME,
                    Olympiad.external_id.in_(external_ids),
                )
            )
        )
        if not olympiads:
            stats.unmatched.append(
                f"activity_id={activity_id}: id {', '.join(external_ids)} нет в базе"
            )
            continue

        for olympiad in olympiads:
            olympiad.source_checked_at = checked_at
            await _sync_stages(session, olympiad, payloads, entry, stats)
            stats.olympiads_matched += 1

    await session.commit()
    logger.info("Импорт расписания завершён: %s", stats.as_dict())
    return stats


async def _sync_stages(
    session: AsyncSession,
    olympiad: Olympiad,
    payloads: Sequence[Dict[str, Any]],
    entry: Dict[str, Any],
    stats: ScheduleImportStats,
) -> None:
    current = list(
        await session.scalars(select(Stage).where(Stage.olympiad_id == olympiad.id))
    )
    by_key = {stage.external_key: stage for stage in current}
    source_url = (entry.get("url") or "").strip()[:1024] or None

    seen: Set[str] = set()
    for position, payload in enumerate(payloads):
        name = (payload.get("name_stage") or "").strip()
        if not name:
            stats.skipped_stages.append(f"{olympiad.name}: этап без названия")
            continue

        key = stage_external_key(name, seen)
        seen.add(key)

        stage = by_key.get(key)
        if stage is None:
            stage = Stage(olympiad_id=olympiad.id, external_key=key)
            session.add(stage)
            stats.stages_created += 1
        else:
            stats.stages_updated += 1

        stage.name = name
        stage.kind = classify_stage(name)
        stage.position = position

        starts_on, start_precision, ends_on, end_precision = stage_dates(payload)
        stage.starts_on = starts_on
        stage.start_precision = start_precision
        stage.ends_on = ends_on
        stage.end_precision = end_precision

        # Исходная строка источника: интерфейс показывает её там, где
        # точности не хватает, а при разборе споров она — единственное
        # свидетельство того, что видел парсер.
        stage.raw_date_range = (payload.get("source_text") or "").strip()[:255] or None
        stage.source_url = source_url

    # Этапов, которых в источнике больше нет, быть не должно и у нас:
    # решено держать только данные olimpiada.ru.
    for key, stage in by_key.items():
        if key not in seen:
            await session.delete(stage)
            stats.stages_removed += 1
