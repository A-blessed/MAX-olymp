"""Очередь отправки с учётом лимита MAX.

Платформа разрешает не более 2 сообщений в секунду в один диалог, чат
или канал. Лимит считается на получателя, поэтому очередь тоже на
получателя: сообщения разным пользователям не блокируют друг друга.

Без такой очереди рассылка в цикле частично отваливается — это одна из
типовых ошибок при работе с API MAX.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Hashable

logger = logging.getLogger(__name__)

# 2 сообщения в секунду -> минимум 0.5 с между отправками.
# Небольшой запас страхует от расхождения часов и сетевого джиттера.
DEFAULT_MIN_INTERVAL = 0.55

# Сколько получателей держим в памяти, прежде чем чистить неактивных.
_PRUNE_THRESHOLD = 10_000


class PerTargetRateLimiter:
    """Пропускает не чаще одного вызова в ``min_interval`` секунд на ключ."""

    def __init__(self, min_interval: float = DEFAULT_MIN_INTERVAL) -> None:
        self.min_interval = min_interval
        self._locks: Dict[Hashable, asyncio.Lock] = {}
        self._next_allowed: Dict[Hashable, float] = {}

    async def acquire(self, key: Hashable) -> None:
        """Ждёт, пока для ``key`` можно будет выполнить следующую отправку."""
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks.setdefault(key, asyncio.Lock())

        # Лок держим и во время сна: так параллельные отправки одному
        # получателю выстраиваются в очередь, а не стартуют одновременно.
        async with lock:
            loop = asyncio.get_running_loop()
            wait_for = self._next_allowed.get(key, 0.0) - loop.time()
            if wait_for > 0:
                logger.debug("Лимит MAX: ждём %.2f с перед отправкой в %s", wait_for, key)
                await asyncio.sleep(wait_for)
            self._next_allowed[key] = loop.time() + self.min_interval

        self._maybe_prune()

    def _maybe_prune(self) -> None:
        """Убирает получателей, для которых окно лимита давно истекло."""
        if len(self._next_allowed) < _PRUNE_THRESHOLD:
            return
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            return
        stale = [
            key
            for key, allowed_at in self._next_allowed.items()
            if allowed_at < now and not (key in self._locks and self._locks[key].locked())
        ]
        for key in stale:
            self._next_allowed.pop(key, None)
            self._locks.pop(key, None)
        logger.debug("Очистили %d неактивных получателей из лимитера", len(stale))
