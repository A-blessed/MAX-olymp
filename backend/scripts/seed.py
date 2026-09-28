"""Наполнить пустой каталог выгрузками из data/ — при первом старте.

    python -m scripts.seed

Вызывается командой контейнера сразу после миграций, поэтому
`docker compose up` поднимает не пустую оболочку, а приложение с
каталогом и датами этапов: проверка решения не требует ручных шагов.

Если в каталоге уже есть хоть одна олимпиада, скрипт ничего не делает.
Обновлять данные на живой базе — осознанный шаг, а не побочный эффект
перезапуска:

    python -m scripts.import_subjects
    python -m scripts.import_schedule
    python -m scripts.import_catalog
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import func, select

from app.catalog.importer import import_olympiads, load_rows
from app.catalog.models import Olympiad
from app.catalog.schedule_importer import import_schedules
from app.catalog.subject_importer import import_subject_tree
from app.db.session import dispose_engine, get_session_factory

from .import_catalog import DEFAULT_FILE as DEFAULT_PARSED
from .import_schedule import DEFAULT_CATALOG, DEFAULT_SCHEDULE
from .import_subjects import DEFAULT_FILE as DEFAULT_SUBJECTS


def _read(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


async def main() -> int:
    try:
        async with get_session_factory()() as session:
            count = await session.scalar(select(func.count()).select_from(Olympiad))
            if count:
                print(f"Каталог уже наполнен (олимпиад: {count}) — импорт не нужен")
                return 0

            print("Каталог пуст — импортируем выгрузки из data/")

            subjects = await import_subject_tree(session, _read(DEFAULT_SUBJECTS))
            print(f"{DEFAULT_SUBJECTS}: {json.dumps(subjects.as_dict(), ensure_ascii=False)}")

            # Расписание кладётся в олимпиады каталога, поэтому идёт вторым.
            schedule = await import_schedules(
                session, _read(DEFAULT_SCHEDULE), _read(DEFAULT_CATALOG)
            )
            print(f"{DEFAULT_SCHEDULE}: {json.dumps(schedule.as_dict(), ensure_ascii=False)}")

            # Второй источник: в интерфейсе его записи не видны — предмета
            # у них нет, — но на них проверяются этапы с датой до месяца
            # (scripts.smoke_test), а в выгрузке по предметам таких нет.
            parsed = await import_olympiads(session, load_rows(DEFAULT_PARSED))
            print(f"{DEFAULT_PARSED}: {json.dumps(parsed.as_dict(), ensure_ascii=False)}")
    finally:
        await dispose_engine()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
