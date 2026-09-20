"""Генерация подписанной строки запуска для ручной проверки API.

Нужна, чтобы проверять эндпоинты мини-приложения, пока фронтенд ещё не
готов или пока нет доступа к самому MAX.

    docker compose run --rm backend python -m scripts.make_launch_data

Строка подписывается вашим BOT_TOKEN, поэтому сервер примет её как
настоящую. Использовать только локально.
"""

from __future__ import annotations

import argparse
import sys
import time

from app.config import get_settings
from app.security.testing import build_signed_launch_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Подписанные данные запуска для отладки")
    parser.add_argument("--user-id", type=int, default=1234567)
    parser.add_argument("--first-name", default="Тест")
    parser.add_argument("--start-param", default=None, help="метка запуска из диплинка")
    parser.add_argument(
        "--age",
        type=int,
        default=0,
        help="насколько секунд состарить auth_date (для проверки TTL)",
    )
    parser.add_argument("--curl", action="store_true", help="вывести готовую команду curl")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()

    if not settings.bot_token:
        print("BOT_TOKEN не задан — подписывать нечем.")
        return 1

    raw = build_signed_launch_data(
        settings.bot_token,
        user_id=args.user_id,
        first_name=args.first_name,
        start_param=args.start_param,
        auth_date=int(time.time()) - args.age,
    )

    if args.curl:
        print(f'curl -s http://localhost:8000/api/me -H "Authorization: tma {raw}"')
    else:
        print(raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
