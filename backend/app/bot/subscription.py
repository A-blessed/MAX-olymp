"""Подписка бота на события MAX: оформлена ли она на наш адрес.

Без подписки MAX не присылает бэкенду ничего: ни «пользователь запустил
бота», ни сообщений. Снаружи при этом всё выглядит живым — мини-приложение
открывается, API отвечает, — а бот молчит, в ``bot_dialogs`` пусто, и
утренние сводки уходить некому. «Бот запущен, но ничего не работает».

Подписка пропадает сама: MAX снимает её после 8 часов неудачных доставок —
бэкенд лежал, туннель закрылся, секрет не совпал. Поэтому бэкенд смотрит
на неё при каждом старте и пишет в лог одну строку с тем, что делать.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import Settings
from ..max_api.client import MaxApiClient

logger = logging.getLogger(__name__)

# События, на которые подписывает scripts.setup_webhook. Полный список —
# в описании объекта Update.
UPDATE_TYPES: List[str] = [
    "bot_started",
    "bot_stopped",
    "dialog_removed",
    "message_created",
    "message_callback",
]

SETUP_COMMAND = "python -m scripts.setup_webhook"


def _same_url(left: str, right: str) -> bool:
    return left.strip().rstrip("/").lower() == right.strip().rstrip("/").lower()


@dataclass
class SubscriptionState:
    """Что MAX знает о подписках бота."""

    url: str
    # Подписка на наш адрес, как её вернул MAX; None — её нет.
    ours: Optional[Dict[str, Any]] = None
    # Адреса остальных подписок: туда события уходят вместо нас.
    others: List[str] = field(default_factory=list)

    @property
    def subscribed(self) -> bool:
        return self.ours is not None

    @property
    def missing_types(self) -> List[str]:
        """Нужные события, которых в подписке нет."""
        if self.ours is None:
            return list(UPDATE_TYPES)
        types = self.ours.get("update_types")
        # Пустой список или его отсутствие — подписка на все события.
        if not types:
            return []
        return [name for name in UPDATE_TYPES if name not in types]


def parse_subscriptions(payload: Any, url: str) -> SubscriptionState:
    """Разбирает ответ ``GET /subscriptions``: ``{"subscriptions": [...]}``."""
    items = payload.get("subscriptions") if isinstance(payload, dict) else payload
    state = SubscriptionState(url=url)
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        if state.ours is None and _same_url(str(item["url"]), url):
            state.ours = item
        else:
            state.others.append(str(item["url"]))
    return state


def describe(state: SubscriptionState) -> List[str]:
    """Состояние подписки по-человечески: первая строка — главное."""
    if not state.subscribed:
        lines = [
            f"MAX не присылает события на {state.url}: подписки на этот адрес нет. "
            "Бот не узнает, что его запустили, не ответит на сообщения, и "
            f"утренние сводки уходить будет некому. Исправляется командой: {SETUP_COMMAND}"
        ]
    elif state.missing_types:
        lines = [
            f"Подписка на {state.url} есть, но без событий {', '.join(state.missing_types)}. "
            f"Перерегистрируйте её: {SETUP_COMMAND}"
        ]
    else:
        lines = [f"Подписка на события MAX: {state.url}"]

    where = "ещё и на" if state.subscribed else "сейчас на"
    for other in state.others:
        lines.append(
            f"События уходят {where} {other}. Если это старый адрес, снимите "
            f"подписку: {SETUP_COMMAND} --delete --url {other}"
        )
    return lines


async def fetch_state(client: MaxApiClient, settings: Settings) -> SubscriptionState:
    return parse_subscriptions(await client.list_subscriptions(), settings.webhook_url)


async def log_subscription(client: MaxApiClient, settings: Settings) -> None:
    """Проверка при старте: одна строка в лог, падать нечему."""
    try:
        state = await fetch_state(client, settings)
    except Exception as exc:  # noqa: BLE001 - проверка при старте не должна ничего ронять
        logger.warning("Не удалось проверить подписку на события MAX: %s", exc)
        return

    first, *rest = describe(state)
    if not state.subscribed:
        logger.error(first)
    elif state.missing_types:
        logger.warning(first)
    else:
        logger.info(first)
    for line in rest:
        logger.warning(line)
