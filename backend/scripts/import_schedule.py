"""Импорт расписания этапов, снятого с olimpiada.ru.

    python -m scripts.import_schedule
    python -m scripts.import_schedule --schedule data/olympiads_schedule.json

Нужны два файла. Первый — выгрузка парсера с этапами, сгруппированными
по ``activity_id``. Второй — каталог, размеченный этими же
``activity_id``: в базе их нет, и связать расписание с олимпиадами можно
только через него. Каталог при этом не импортируется, он читается как
таблица соответствия.

Сам парсер лежит в tools/olympiad_schedule_parser.py и запускается
отдельно: он ходит в интернет, и держать его в цикле деплоя незачем.

Повторный запуск безопасен: этапы обновляются на месте по названию.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

from app.catalog.schedule_importer import build_activity_index, import_schedules
from app.db.session import dispose_engine, get_session_factory

DEFAULT_SCHEDULE = "data/olympiads_schedule.json"
DEFAULT_CATALOG = "data/subjects.olimpiada.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Импорт расписания этапов")
    parser.add_argument("--schedule", default=DEFAULT_SCHEDULE, help="выгрузка парсера")
    parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG,
        help="каталог с activity_id — нужен, чтобы связать расписание с базой",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help=(
            "убрать этапы у олимпиад, которых нет в этом импорте. "
            "Вместе с ними уйдёт и отмеченный по ним прогресс"
        ),
    )
    return parser


def _read(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


async def main() -> int:
    args = build_parser().parse_args()

    try:
        schedule = _read(args.schedule)
        catalog = _read(args.catalog)
    except FileNotFoundError as exc:
        print(f"Файл не найден: {exc.filename}")
        return 1
    except ValueError as exc:
        print(f"Не удалось прочитать файл: {exc}")
        return 1

    schedules = schedule.get("schedules")
    if not isinstance(schedules, dict):
        print(f"В {args.schedule} нет объекта 'schedules' — это не выгрузка парсера")
        return 1

    index = build_activity_index(catalog)
    if not index:
        print(
            f"В {args.catalog} нет ни одного activity_id.\n"
            "Связать расписание с базой не по чему: нужен каталог, размеченный "
            "идентификаторами olimpiada.ru."
        )
        return 1

    with_stages = sum(1 for entry in schedules.values() if entry.get("stages"))
    print(
        f"Читаем {args.schedule}: олимпиад — {len(schedules)}, "
        f"из них с расписанием — {with_stages}"
    )
    print(f"Соответствий activity_id в {args.catalog}: {len(index)}")

    try:
        async with get_session_factory()() as session:
            stats = await import_schedules(session, schedule, catalog, prune=args.prune)
    finally:
        await dispose_engine()

    for title, value in stats.as_dict().items():
        print(f"  {title}: {value}")

    # Несопоставленные — не мелочь: это олимпиады, расписание которых
    # собрали, но положить некуда. Лучше увидеть их сразу.
    if stats.unmatched:
        print(f"\nНе нашлось в базе ({len(stats.unmatched)}):")
        for line in stats.unmatched[:10]:
            print(f"  {line}")
        if len(stats.unmatched) > 10:
            print(f"  … и ещё {len(stats.unmatched) - 10}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
