"""Endpoint вебхука для событий бота.

Порядок обработки по документации MAX:
вызов endpoint → TLS-валидация → HTTPS-запрос → проверка секрета →
200 OK → обработка события → вызовы API MAX.

Ключевое: 200 OK должен уйти до обработки. У платформы есть 30 секунд,
после чего доставка считается неуспешной; при неудачах идут повторы, а
через 8 часов без успешного ответа бот отписывается от вебхука
автоматически. Поэтому здесь ответ отдаётся сразу, а вся работа уходит
в фоновую задачу.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status

from ..config import Settings, get_settings
from ..max_api.client import MaxApiClient
from ..security.deps import get_max_client
from .handlers import dispatch

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bot"])

SECRET_HEADER = "X-Max-Bot-Api-Secret"


def _verify_secret(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided, expected)


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def receive_update(
    request: Request,
    background: BackgroundTasks,
    x_max_bot_api_secret: str = Header(default=""),
    settings: Settings = Depends(get_settings),
    client: MaxApiClient = Depends(get_max_client),
) -> Dict[str, Any]:
    """Принимает объект Update от MAX."""
    # Секрет задаётся при подписке и приходит в каждом запросе.
    # Без этой проверки вебхук может дёрнуть кто угодно, кто знает адрес.
    if settings.webhook_secret:
        if not _verify_secret(x_max_bot_api_secret, settings.webhook_secret):
            logger.warning("Отклонён вебхук с неверным %s", SECRET_HEADER)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Неверный секрет вебхука",
            )
    elif settings.is_production:
        # В проде отсутствие секрета — дыра, а не мелочь.
        logger.error("WEBHOOK_SECRET не задан в production — вебхук никак не защищён")

    try:
        update = await request.json()
    except ValueError:
        logger.warning("Вебхук получил тело, которое не является JSON")
        # Отвечаем 200: повторная доставка того же битого тела не поможет.
        return {"ok": True}

    if not isinstance(update, dict):
        logger.warning("Вебхук получил JSON неожиданного типа: %s", type(update).__name__)
        return {"ok": True}

    logger.info("Получено событие %s", update.get("update_type"))

    # Задача выполнится после того, как ответ уже уйдёт клиенту.
    background.add_task(dispatch, update, client, settings)

    return {"ok": True}
