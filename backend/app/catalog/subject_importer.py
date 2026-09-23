"""Импорт файла олимпиад, сгруппированных по предметам.

Формат источника::

    {"subjects": [{"name": "Физика",
                   "olympiads": [{"name": ..., "level": "I", "grades": ...,
                                  "official_url": ..., "description": ...,
                                  "id": "576", "organizers": ...}]}]}

Главное, что выясняется из данных: одна олимпиада идёт сразу по многим
предметам, и уровень у неё **по каждому предмету свой**. Московская
олимпиада по астрономии — I уровня, по биологии — II. Поэтому в базу
пишется запись на каждую пару «олимпиада + предмет», а не одна запись на
олимпиаду: иначе уровень пришлось бы выбирать наугад.

Описание, ссылка, классы и организаторы у всех предметов одной олимпиады
совпадают — это проверено по файлу, — поэтому они просто дублируются.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Olympiad, Subject

logger = logging.getLogger(__name__)

# Имя источника: отличает эти записи от выгрузки парсера postupi.online.
SOURCE_NAME = "subjects-file"

# Ключ с организаторами переименовали из кириллического в латинский;
# читаем оба, чтобы импорт не зависел от версии файла.
ORGANIZERS_KEYS = ("organizers", "организаторы")

# Строка, которой источник обозначает отсутствие данных. Встречается и
# в классах, и в организаторах — пустых значений в файле нет вообще,
# поэтому без этой проверки «Нет информации» уехало бы на карточку как
# имя организатора.
NO_DATA = "нет информации"

# Справочник предметов. Идентификаторы и цвета совпадают со списком
# SUBJECTS во фронтенде — так карточки красятся одинаково с обеих сторон,
# и никому не нужно ничего сопоставлять руками.
#
# Короткий код используется в режиме для дальтоников: рядом с цветным
# кружком выводится «МАТ», «ФИЗ» и так далее.
SUBJECT_CATALOG: Tuple[Tuple[int, str, str, str, str], ...] = (
    (1, "astronomy", "Астрономия", "#FFE0B2", "АСТ"),
    (2, "biology", "Биология", "#F4B3C4", "БИО"),
    (3, "geography", "География", "#E9C2E8", "ГЕО"),
    (4, "foreign-language", "Иностранный язык", "#D4A5F7", "ИНЯ"),
    (5, "informatics", "Информатика", "#C9CFF5", "ИНФ"),
    (6, "history", "История", "#A8D8FF", "ИСТ"),
    (7, "literature", "Литература", "#B2E6F5", "ЛИТ"),
    (8, "mathematics", "Математика", "#8FDCE0", "МАТ"),
    (9, "social-studies", "Обществознание", "#A7D9B5", "ОБЩ"),
    (10, "law", "Право", "#C5E6B0", "ПРА"),
    (11, "russian", "Русский язык", "#FFF0B3", "РУС"),
    (12, "physics", "Физика", "#F5E6C8", "ФИЗ"),
    (13, "chemistry", "Химия", "#BAAC9B", "ХИМ"),
    (14, "economics", "Экономика", "#BFBAB4", "ЭКО"),
)

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}

# Поля, которые мы умеем читать. Всё остальное попадёт в отчёт импорта —
# так появление дат в файле не пройдёт незамеченным.
KNOWN_KEYS = {"name", "level", "grades", "official_url", "description", "id"} | set(
    ORGANIZERS_KEYS
)


def parse_levels(raw: Any) -> List[int]:
    """«I» → [1]; ['II', 'III'] → [2, 3].

    По одному предмету олимпиада иногда проходит сразу на нескольких
    уровнях, поэтому результат всегда список.
    """
    if raw is None:
        return []
    values = raw if isinstance(raw, (list, tuple)) else [raw]

    levels: List[int] = []
    for value in values:
        token = str(value).strip().upper()
        level = _ROMAN.get(token)
        if level is None and token.isdigit():
            level = int(token)
        if level is not None and level not in levels:
            levels.append(level)
    return sorted(levels)


def clean_text(raw: Any) -> Optional[str]:
    """Схлопывает пробелы и превращает заглушку источника в ``None``."""
    if not raw:
        return None
    text = re.sub(r"\s+", " ", str(raw)).strip()
    if not text or text.lower().startswith(NO_DATA):
        return None
    return text


def parse_grades(raw: Any) -> Optional[str]:
    """Нормализует классы участников. «Нет информации» → ``None``."""
    text = clean_text(raw)
    return text[:64] if text else None


def pick_organizers(payload: Dict[str, Any]) -> Optional[str]:
    """Организаторы из того ключа, который есть в этой версии файла."""
    for key in ORGANIZERS_KEYS:
        text = clean_text(payload.get(key))
        if text:
            return text
    return None


@dataclass
class SubjectImportStats:
    subjects_created: int = 0
    olympiads_created: int = 0
    olympiads_updated: int = 0
    skipped: List[str] = field(default_factory=list)
    unique_olympiads: int = 0
    # Ключи источника, которых мы пока не читаем: сюда попадут будущие
    # поля с датами, когда они появятся в файле.
    unknown_keys: Set[str] = field(default_factory=set)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "subjects_created": self.subjects_created,
            "olympiads_created": self.olympiads_created,
            "olympiads_updated": self.olympiads_updated,
            "unique_olympiads": self.unique_olympiads,
            "skipped": self.skipped,
            "unknown_keys": sorted(self.unknown_keys),
        }


async def ensure_subjects(
    session: AsyncSession, stats: Optional["SubjectImportStats"] = None
) -> Dict[str, Subject]:
    """Создаёт справочник предметов, если его ещё нет. Возвращает по имени."""
    existing = {s.slug: s for s in await session.scalars(select(Subject))}
    created = 0

    for subject_id, slug, name, color, short_code in SUBJECT_CATALOG:
        subject = existing.get(slug)
        if subject is None:
            subject = Subject(id=subject_id, slug=slug)
            session.add(subject)
            created += 1
        subject.name = name
        subject.color = color
        subject.short_code = short_code
        existing[slug] = subject

    await session.flush()
    if stats is not None:
        stats.subjects_created = created
    if created:
        logger.info("Создано предметов: %d", created)
    return {subject.name: subject for subject in existing.values()}


async def import_subject_tree(
    session: AsyncSession, data: Dict[str, Any]
) -> SubjectImportStats:
    """Записывает файл в каталог. Повторный запуск безопасен."""
    stats = SubjectImportStats()
    by_name = await ensure_subjects(session, stats)
    checked_at = datetime.now(timezone.utc)

    # Уже существующие записи этого источника — чтобы обновлять их, а не
    # плодить новые: на строки каталога ссылается прогресс пользователя.
    existing_rows = await session.scalars(
        select(Olympiad).where(Olympiad.source == SOURCE_NAME)
    )
    existing = {(row.external_id, row.subject_id): row for row in existing_rows}

    seen_ids: Set[str] = set()

    for subject_block in data.get("subjects") or []:
        subject_name = (subject_block.get("name") or "").strip()
        subject = by_name.get(subject_name)
        if subject is None:
            stats.skipped.append(f"неизвестный предмет: {subject_name or '<пусто>'}")
            continue

        for payload in subject_block.get("olympiads") or []:
            external_id = str(payload.get("id") or "").strip()
            name = (payload.get("name") or "").strip()
            if not external_id or not name:
                stats.skipped.append(name or f"{subject_name}: запись без id")
                continue

            stats.unknown_keys |= set(payload) - KNOWN_KEYS
            seen_ids.add(external_id)

            olympiad = existing.get((external_id, subject.id))
            if olympiad is None:
                olympiad = Olympiad(
                    source=SOURCE_NAME,
                    external_id=external_id,
                    subject_id=subject.id,
                )
                session.add(olympiad)
                stats.olympiads_created += 1
            else:
                stats.olympiads_updated += 1

            levels = parse_levels(payload.get("level"))
            olympiad.name = name
            olympiad.levels = levels
            # Для сортировки «от I к III» нужен один уровень — берём лучший.
            olympiad.level = levels[0] if levels else None
            olympiad.grades = parse_grades(payload.get("grades"))
            olympiad.summary = clean_text(payload.get("description"))
            olympiad.official_url = clean_text(payload.get("official_url"))
            olympiad.organizers = pick_organizers(payload)
            olympiad.source_checked_at = checked_at

    stats.unique_olympiads = len(seen_ids)
    await session.commit()

    if stats.unknown_keys:
        logger.warning(
            "В файле появились неизвестные поля: %s. Их никто не читает — "
            "возможно, пора доработать импорт.",
            ", ".join(sorted(stats.unknown_keys)),
        )
    logger.info("Импорт по предметам завершён: %s", stats.as_dict())
    return stats
