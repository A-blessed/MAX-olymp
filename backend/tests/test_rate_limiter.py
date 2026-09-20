"""Тесты очереди отправки.

MAX разрешает не более 2 сообщений в секунду в один диалог. Лимит
считается на получателя, поэтому проверяем две вещи: последовательные
отправки одному адресату притормаживаются, а разные адресаты друг друга
не блокируют.
"""

from __future__ import annotations

import asyncio

from app.max_api.rate_limiter import PerTargetRateLimiter

# В тестах интервал маленький, чтобы не растягивать прогон.
INTERVAL = 0.05


async def test_same_target_is_throttled():
    limiter = PerTargetRateLimiter(min_interval=INTERVAL)
    loop = asyncio.get_running_loop()

    started = loop.time()
    for _ in range(3):
        await limiter.acquire(("user", 1))
    elapsed = loop.time() - started

    # Первый вызов проходит сразу, следующие два ждут по интервалу.
    assert elapsed >= INTERVAL * 2


async def test_different_targets_do_not_block_each_other():
    limiter = PerTargetRateLimiter(min_interval=INTERVAL)
    loop = asyncio.get_running_loop()

    started = loop.time()
    await asyncio.gather(*(limiter.acquire(("user", user_id)) for user_id in range(10)))
    elapsed = loop.time() - started

    assert elapsed < INTERVAL


async def test_concurrent_sends_to_one_target_are_serialised():
    limiter = PerTargetRateLimiter(min_interval=INTERVAL)
    loop = asyncio.get_running_loop()

    started = loop.time()
    await asyncio.gather(*(limiter.acquire(("chat", 99)) for _ in range(4)))
    elapsed = loop.time() - started

    # Параллельный вызов не должен обходить лимит: 4 отправки -> 3 паузы.
    assert elapsed >= INTERVAL * 3
