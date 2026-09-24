"""Импорт файла олимпиад, сгруппированных по предметам.

    docker compose run --rm backend python -m scripts.import_subjects
    docker compose run --rm backend python -m scripts.import_subjects --file data/subjects.sample.json

Повторный запуск безопасен: записи обновляются на месте.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.catalog.subject_importer import import_subject_tree
from app.db.session import dispose_engine, get_session_factory

DEFAULT_FILE = "data/subjects.sample.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Импорт олимпиад по предметам")
    parser.add_argument("--file", default=DEFAULT_FILE, help="путь к JSON")
    return parser


async def main() -> int:
    args = build_parser().parse_args()

    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Файл не найден: {args.file}")
        return 1
    except ValueError as exc:
        print(f"Не удалось прочитать файл: {exc}")
        return 1

    if not isinstance(data, dict) or "subjects" not in data:
        print("Ожидался объект с ключом 'subjects'")
        return 1

    total = sum(len(s.get("olympiads") or []) for s in data["subjects"])
    print(f"Читаем {args.file}: предметов — {len(data['subjects'])}, записей — {total}")

    try:
        async with get_session_factory()() as session:
            stats = await import_subject_tree(session, data)
    finally:
        await dispose_engine()

    print(json.dumps(stats.as_dict(), ensure_ascii=False, indent=2))
    if stats.duplicate_keys:
        print()
        print(f"Пропущено из-за повторного «id + предмет»: {len(stats.duplicate_keys)}")
        for item in stats.duplicate_keys:
            print(f"  - {item}")
        print("В источнике под одним идентификатором лежат разные олимпиады —")
        print("данные не угадываем, нужно поправить файл.")
    if stats.unknown_keys:
        print("\nВ файле есть поля, которые импорт пока не читает:")
        for key in sorted(stats.unknown_keys):
            print(f"  - {key}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
