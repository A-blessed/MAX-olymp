"""Импорт выгрузки источника в базу.

Источник отдаёт плоский JSON; здесь он превращается в каталог: даты
разбираются, этапы получают тип, записи обновляются вместо пересоздания.

Обновление на месте принципиально: прогресс пользователя («прошёл /
не прошёл») ссылается на этап, и пересоздание строк обнулило бы его при
каждом обновлении данных.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .dates import parse_date, parse_range
from .models import Olympiad, Stage, StageKind

logger = logging.getLogger(__name__)

# Порядок правил важен: «Регистрация на заключительный этап» — это
# регистрация, а не заключительный этап.
_KIND_RULES: Sequence[tuple] = (
    (StageKind.REGISTRATION, re.compile(r"^\s*регистрация", re.IGNORECASE)),
    (StageKind.FINAL, re.compile(r"заключительн|финальн|финал", re.IGNORECASE)),
    (
        StageKind.QUALIFYING,
        re.compile(
            r"отборочн|квалификацион|пригласительн|тренировочн|подготовительн|ознакомительн",
            re.IGNORECASE,
        ),
    ),
)


def classify_stage(name: str) -> StageKind:
    """Определяет тип этапа по названию.

    Источник тип не размечает, поэтому это эвристика. ``OTHER`` —
    честный ответ «не удалось определить», а не мусорная корзина:
    интерфейсу лучше показать название как есть, чем соврать.
    """
    for kind, pattern in _KIND_RULES:
        if pattern.search(name or ""):
            return kind
    return StageKind.OTHER


def build_external_key(stage: Dict[str, Any]) -> str:
    """Устойчивый идентификатор этапа внутри олимпиады.

    Берём слаг из ссылки источника — он не меняется при правке названия.
    Если ссылки нет, откатываемся на нормализованное название.
    """
    url = (stage.get("url") or "").strip()
    if url:
        segments = [segment for segment in url.rstrip("/").split("/") if segment]
        if segments:
            return segments[-1][:255]

    normalized = re.sub(r"\s+", " ", (stage.get("name") or "")).strip().lower()
    return (normalized or "stage")[:255]


@dataclass
class ImportStats:
    """Что именно сделал импорт — попадает в лог и в ответ скрипта."""

    olympiads_created: int = 0
    olympiads_updated: int = 0
    stages_created: int = 0
    stages_updated: int = 0
    stages_removed: int = 0
    skipped: List[str] = field(default_factory=list)
    stage_kinds: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "olympiads_created": self.olympiads_created,
            "olympiads_updated": self.olympiads_updated,
            "stages_created": self.stages_created,
            "stages_updated": self.stages_updated,
            "stages_removed": self.stages_removed,
            "skipped": self.skipped,
            "stage_kinds": self.stage_kinds,
        }


def _apply_dates(stage: Stage, payload: Dict[str, Any]) -> None:
    """Проставляет даты, предпочитая отдельные поля, а не общий диапазон."""
    start = parse_date(payload.get("start_date") or "")
    end = parse_date(payload.get("end_date") or "")

    if start is None and end is None:
        start, end = parse_range(payload.get("date_range") or "")

    stage.starts_on = start.value if start else None
    stage.start_precision = start.precision if start else None
    stage.ends_on = end.value if end else None
    stage.end_precision = end.precision if end else None
    stage.raw_date_range = (payload.get("date_range") or "").strip()[:255] or None


async def import_olympiads(
    session: AsyncSession,
    rows: Iterable[Dict[str, Any]],
    *,
    source: str = "postupi.online",
) -> ImportStats:
    """Записывает выгрузку в каталог. Повторный запуск безопасен."""
    stats = ImportStats()
    checked_at = datetime.now(timezone.utc)

    for row in rows:
        url = (row.get("url") or "").strip()
        name = (row.get("name") or "").strip()

        if not url or not name:
            # Запись без ссылки нечем идентифицировать при следующем импорте.
            stats.skipped.append(name or url or "<пустая запись>")
            continue

        existing = await session.scalar(
            select(Olympiad).where(Olympiad.source_url == url)
        )

        if existing is None:
            olympiad = Olympiad(source=source, source_url=url, name=name)
            session.add(olympiad)
            stats.olympiads_created += 1
            # Нужен id для привязки этапов.
            await session.flush()
        else:
            olympiad = existing
            olympiad.name = name
            stats.olympiads_updated += 1

        olympiad.source_checked_at = checked_at
        olympiad.partner_universities = list(row.get("universities") or [])

        await _sync_stages(session, olympiad, row.get("stages") or [], stats)

    await session.commit()
    logger.info("Импорт завершён: %s", stats.as_dict())
    return stats


async def _sync_stages(
    session: AsyncSession,
    olympiad: Olympiad,
    payloads: Sequence[Dict[str, Any]],
    stats: ImportStats,
) -> None:
    current = await session.scalars(
        select(Stage).where(Stage.olympiad_id == olympiad.id)
    )
    by_key: Dict[str, Stage] = {stage.external_key: stage for stage in current}
    seen: set = set()

    for position, payload in enumerate(payloads):
        key = build_external_key(payload)
        if key in seen:
            # Два этапа с одинаковым ключом — берём первый, иначе upsert
            # начнёт перетирать одну и ту же строку в пределах импорта.
            logger.warning("Повтор ключа этапа %r у %s", key, olympiad.source_url)
            continue
        seen.add(key)

        stage = by_key.get(key)
        if stage is None:
            stage = Stage(olympiad_id=olympiad.id, external_key=key)
            session.add(stage)
            stats.stages_created += 1
        else:
            stats.stages_updated += 1

        stage.name = (payload.get("name") or "").strip()
        stage.kind = classify_stage(stage.name)
        stage.position = position
        stage.source_url = (payload.get("url") or "").strip() or None
        _apply_dates(stage, payload)

        stats.stage_kinds[stage.kind.value] = stats.stage_kinds.get(stage.kind.value, 0) + 1

    for key, stage in by_key.items():
        if key not in seen:
            # Этап пропал из источника — удаляем, иначе в календаре
            # останется событие, которого больше нет.
            await session.delete(stage)
            stats.stages_removed += 1


def load_rows(path: str) -> List[Dict[str, Any]]:
    """Читает выгрузку парсера из JSON-файла."""
    import json
    from pathlib import Path

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Ожидался список олимпиад, получен {type(data).__name__}")
    return data
