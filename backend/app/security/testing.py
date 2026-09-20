"""Генератор подписанных данных запуска для разработки и тестов.

Позволяет дёргать API мини-приложения без самого MAX: строка собирается
и подписывается ровно тем же алгоритмом, который проверяет сервер.

Модуль намеренно лежит рядом с валидацией, а не в тестах: им пользуются
и тесты, и отладочный скрипт. В рантайме он не вызывается.
"""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from .launch_data import build_launch_params, sign


def build_signed_launch_data(
    bot_token: str,
    *,
    user_id: int = 1234567,
    first_name: str = "Тест",
    last_name: Optional[str] = "Пользователь",
    username: Optional[str] = None,
    language_code: str = "ru",
    auth_date: Optional[int] = None,
    chat: Optional[dict] = None,
    query_id: str = "00000000-0000-0000-0000-000000000000",
    start_param: Optional[str] = None,
    extra: Optional[Dict[str, str]] = None,
) -> str:
    """Собирает строку WebAppData с корректной подписью.

    Возвращает значение в том виде, в каком его присылает фронтенд:
    пары ``key=value``, склеенные через ``&``, значения закодированы
    ровно один раз.
    """
    user = {
        "id": user_id,
        "first_name": first_name,
        "last_name": last_name,
        "username": username,
        "language_code": language_code,
        "photo_url": None,
    }

    # separators без пробелов — так же, как отдаёт платформа.
    values: Dict[str, str] = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": query_id,
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
    }
    if chat is not None:
        values["chat"] = json.dumps(chat, ensure_ascii=False, separators=(",", ":"))
    if start_param is not None:
        values["start_param"] = start_param
    if extra:
        values.update(extra)

    # Подпись считается по декодированным значениям.
    decoded_pairs: List[Tuple[str, str]] = list(values.items())
    signature = sign(bot_token, build_launch_params(decoded_pairs))

    # А передаётся строка с закодированными значениями.
    encoded = "&".join(f"{key}={quote(value, safe='')}" for key, value in decoded_pairs)
    return f"{encoded}&hash={signature}"
