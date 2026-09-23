"""Импорт выгрузки парсера в каталог.

    docker compose run --rm backend python -m scripts.import_catalog
    docker compose run --rm backend python -m scripts.import_catalog --file data/olympiads.sample.json

Повторный запуск безопасен: записи обновляются на месте, а не дублируются.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.catalog.importer import import_olympiads, load_rows
from app.db.session import dispose_engine, get_session_factory, init_models

DEFAULT_FILE = "data/olympiads.sample.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Импорт олимпиад в каталог")
    parser.add_argument("--file", default=DEFAULT_FILE, help="путь к JSON парсера")
    return parser


async def main() -> int:
    args = build_parser().parse_args()

    try:
        rows = load_rows(args.file)
    except FileNotFoundError:
        print(f"Файл не найден: {args.file}")
        return 1
    except ValueError as exc:
        print(f"Не удалось прочитать выгрузку: {exc}")
        return 1

    print(f"Читаем {args.file}: олимпиад — {len(rows)}")

    await init_models()
    try:
        async with get_session_factory()() as session:
            stats = await import_olympiads(session, rows)
    finally:
        await dispose_engine()

    print(json.dumps(stats.as_dict(), ensure_ascii=False, indent=2))
    if stats.skipped:
        print(f"\nПропущено записей без ссылки или названия: {len(stats.skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
