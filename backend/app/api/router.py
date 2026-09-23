"""HTTP API мини-приложения.

Здесь лежит только каркас аутентификации. Эндпоинты предметной области
добавляются отдельными роутерами и подключаются в ``main.py`` — так
бизнес-логику можно развивать, не трогая механику проверки подписи.

Правило для всех будущих роутеров: идентификатор пользователя берётся
только из ``Depends(get_current_user)``. Всё, что влияет на доступ или
деньги, пересчитывается на сервере — данным из тела запроса верить нельзя.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..db.models import User
from ..security.deps import get_current_user, get_launch_data
from ..security.launch_data import LaunchData

router = APIRouter(prefix="/api", tags=["mini-app"])


class UserProfile(BaseModel):
    """Профиль пользователя из проверенных данных запуска."""

    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None
    photo_url: Optional[str] = None


class MeResponse(BaseModel):
    user: UserProfile
    # Метка запуска из диплинка (?startapp=...): реферальный код, промо и т. п.
    start_param: Optional[str] = None
    # Возраст подписанной строки запуска в секундах — удобно при отладке TTL.
    launch_age_seconds: int


@router.get("/me", response_model=MeResponse, summary="Текущий пользователь")
async def read_me(
    user: User = Depends(get_current_user),
    data: LaunchData = Depends(get_launch_data),
) -> MeResponse:
    """Возвращает пользователя, подтверждённого подписью данных запуска.

    Первый запрос, который стоит дёрнуть с фронтенда: он проверяет всю
    цепочку целиком — заголовок, подпись, срок годности и запись в БД.
    """
    return MeResponse(
        user=UserProfile(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            language_code=user.language_code,
            photo_url=user.photo_url,
        ),
        start_param=data.start_param,
        launch_age_seconds=data.age_seconds,
    )
