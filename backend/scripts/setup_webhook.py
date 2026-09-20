"""Регистрация вебхука в MAX.

    docker compose run --rm backend python -m scripts.setup_webhook
    docker compose run --rm backend python -m scripts.setup_webhook --list
    docker compose run --rm backend python -m scripts.setup_webhook --delete

Адрес берётся из PUBLIC_BASE_URL и WEBHOOK_PATH. При смене адреса
туннеля подписку нужно перерегистрировать: бесплатный тариф ngrok выдаёт
новый домен при каждом перезапуске.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import List

from app.config import get_settings
from app.max_api.client import MaxApiClient, MaxApiError

# События, которых достаточно для базового сценария.
# Полный список — в описании объекта Update.
DEFAULT_UPDATE_TYPES: List[str] = [
    "bot_started",
    "bot_stopped",
    "dialog_removed",
    "message_created",
    "message_callback",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Управление подпиской на события MAX")
    parser.add_argument("--list", action="store_true", help="показать действующие подписки")
    parser.add_argument("--delete", action="store_true", help="удалить подписку на текущий адрес")
    parser.add_argument("--url", default=None, help="переопределить адрес вебхука")
    return parser


async def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()

    if not settings.bot_token:
        print("BOT_TOKEN не задан.")
        return 1

    client = MaxApiClient(
        token=settings.bot_token,
        base_url=settings.max_api_base_url,
        timeout=settings.max_api_timeout,
        extra_ca_files=settings.extra_ca_files(),
    )

    try:
        if args.list:
            result = await client.list_subscriptions()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        url = args.url or settings.webhook_url

        if not settings.public_base_url and not args.url:
            print("PUBLIC_BASE_URL не задан. Укажите адрес туннеля или передайте --url.")
            return 1

        if args.delete:
            await client.delete_subscription(url)
            print(f"Подписка на {url} удалена")
            return 0

        if not settings.webhook_secret:
            print("ВНИМАНИЕ: WEBHOOK_SECRET пуст — вебхук сможет вызвать кто угодно.")

        result = await client.subscribe_webhook(
            url,
            update_types=DEFAULT_UPDATE_TYPES,
            secret=settings.webhook_secret or None,
        )
        print(f"Подписка оформлена на {url}")
        print(f"События: {', '.join(DEFAULT_UPDATE_TYPES)}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    except MaxApiError as exc:
        print(f"Ошибка: {exc}")
        if exc.payload:
            print(f"Ответ сервера: {exc.payload}")
        return 1
    except ValueError as exc:
        print(f"Ошибка: {exc}")
        return 1
    finally:
        await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
