"""Кнопки сообщений бота."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..config import Settings


def mini_app_button(
    settings: Settings, start_param: str, text: str = "Открыть приложение"
) -> Optional[Dict[str, Any]]:
    """Кнопка-ссылка, открывающая мини-приложение из чата.

    Диплинк вида ``https://max.ru/<botName>?startapp=<payload>``. Без
    ``?startapp=`` ссылка ведёт в профиль бота, а не в мини-приложение.
    В payload допустимы только ``A-Z a-z 0-9 _ -``: остальные символы
    платформа молча вырезает вместе с параметром.

    Значение payload доезжает до бэкенда в данных запуска и показывает,
    откуда пришёл пользователь: из приветствия, из утренней сводки или из
    каталога MAX.
    """
    if not settings.bot_username:
        return None

    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [
                    {
                        "type": "link",
                        "text": text,
                        "url": f"https://max.ru/{settings.bot_username}?startapp={start_param}",
                    }
                ]
            ]
        },
    }
