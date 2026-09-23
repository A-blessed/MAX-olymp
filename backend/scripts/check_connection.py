"""Проверка связи с API MAX.

Первое, что стоит запустить после получения токена: скрипт сразу ловит
три типовые проблемы — неверный домен, отсутствие сертификата Минцифры
в доверенных и недействительный токен.

    docker compose run --rm backend python -m scripts.check_connection
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.config import get_settings
from app.max_api.client import MaxApiClient, MaxApiError


async def main() -> int:
    settings = get_settings()

    if not settings.bot_token:
        print("BOT_TOKEN не задан. Положите токен в .env и повторите.")
        return 1

    ca_files = settings.extra_ca_files()
    print(f"Домен API : {settings.max_api_base_url}")
    print(f"Сертификаты: {', '.join(p.name for p in ca_files) if ca_files else 'нет (ожидается ошибка TLS)'}")
    print()

    client = MaxApiClient(
        token=settings.bot_token,
        base_url=settings.max_api_base_url,
        timeout=settings.max_api_timeout,
        extra_ca_files=ca_files,
    )

    try:
        me = await client.get_me()
    except MaxApiError as exc:
        print(f"Связь не установлена: {exc}")
        if exc.payload:
            print(f"Ответ сервера: {exc.payload}")
        return 1
    finally:
        await client.aclose()

    print("Связь есть. Ответ GET /me:")
    print(json.dumps(me, ensure_ascii=False, indent=2))

    name = me.get("username") or me.get("name")
    if name:
        print(f"\nНик бота для диплинка: {name}")
        print(f"Пропишите его в BOT_USERNAME, чтобы работала ссылка https://max.ru/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
