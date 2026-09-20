"""HTTP-клиент Bot API MAX.

Три вещи, на которых спотыкаются чаще всего, зафиксированы здесь:

1. Домен ``platform-api2.max.ru``. Старый ``platform-api.max.ru`` больше
   не обслуживает ботов и мини-приложения.
2. Токен передаётся только заголовком ``Authorization: <token>``, без
   префикса ``Bearer``. Передача через query-параметр отменена.
3. Сертификат Минцифры должен быть в доверенных, иначе TLS-соединение
   не устанавливается: ``*.max.ru`` подписан ``Russian Trusted Sub CA``,
   которого нет в стандартных наборах корневых сертификатов.
"""

from __future__ import annotations

import logging
import ssl
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import certifi
import httpx

from .rate_limiter import PerTargetRateLimiter

logger = logging.getLogger(__name__)

# Максимальная длина текста сообщения по документации.
MAX_TEXT_LENGTH = 4000


class MaxApiError(RuntimeError):
    """Ошибка вызова Bot API MAX."""

    def __init__(self, message: str, status_code: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def build_ssl_context(extra_ca_files: Iterable[Path] = ()) -> ssl.SSLContext:
    """Стандартные публичные центры сертификации плюс сертификаты Минцифры.

    Важно: httpx по умолчанию использует набор certifi, а не системное
    хранилище. Поэтому добавить сертификат в систему недостаточно — его
    нужно явно подмешать в контекст, что и делает эта функция.
    """
    context = ssl.create_default_context(cafile=certifi.where())
    for path in extra_ca_files:
        try:
            context.load_verify_locations(cafile=str(path))
            logger.info("Добавлен доверенный сертификат: %s", path.name)
        except (ssl.SSLError, OSError) as exc:
            logger.error("Не удалось загрузить сертификат %s: %s", path, exc)
    return context


class MaxApiClient:
    """Асинхронный клиент Bot API MAX.

    Создаётся один раз на приложение и переиспользует пул соединений.
    """

    def __init__(
        self,
        token: str,
        base_url: str = "https://platform-api2.max.ru",
        timeout: float = 15.0,
        extra_ca_files: Iterable[Path] = (),
        rate_limiter: Optional[PerTargetRateLimiter] = None,
    ) -> None:
        if not token:
            raise ValueError("Не задан токен бота (BOT_TOKEN)")

        self._token = token
        self._base_url = base_url.rstrip("/")
        self._limiter = rate_limiter or PerTargetRateLimiter()
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            verify=build_ssl_context(extra_ca_files),
            headers={
                # Именно так: без "Bearer" и не в query-параметре.
                "Authorization": token,
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "MaxApiClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Низкий уровень
    # ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Выполняет запрос и разбирает ответ.

        :raises MaxApiError: при сетевой ошибке, ошибочном статусе или
            ответе вида ``{"success": false}``.
        """
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}

        try:
            response = await self._client.request(method, path, params=clean_params, json=json)
        except httpx.ConnectError as exc:
            # Самая частая причина здесь — отсутствие сертификата Минцифры.
            raise MaxApiError(
                f"Не удалось подключиться к {self._base_url}{path}: {exc}. "
                "Проверьте, что сертификаты Минцифры лежат в каталоге certs/."
            ) from exc
        except httpx.HTTPError as exc:
            raise MaxApiError(f"Сетевая ошибка при вызове {method} {path}: {exc}") from exc

        try:
            payload = response.json()
        except ValueError:
            payload = response.text

        if response.status_code == 401:
            raise MaxApiError(
                "MAX отклонил токен (401). Проверьте BOT_TOKEN и то, что он "
                "передаётся заголовком Authorization без префикса Bearer.",
                status_code=401,
                payload=payload,
            )

        if response.status_code >= 400:
            raise MaxApiError(
                f"{method} {path} вернул {response.status_code}",
                status_code=response.status_code,
                payload=payload,
            )

        # Часть методов отвечает 200 с флагом success=false.
        if isinstance(payload, dict) and payload.get("success") is False:
            raise MaxApiError(
                f"{method} {path}: {payload.get('message') or 'success=false'}",
                status_code=response.status_code,
                payload=payload,
            )

        return payload

    # ------------------------------------------------------------------
    # Методы API
    # ------------------------------------------------------------------

    async def get_me(self) -> Dict[str, Any]:
        """Информация о боте. Удобная проверка связи, домена и сертификатов."""
        return await self.request("GET", "/me")

    async def send_message(
        self,
        text: str,
        *,
        user_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        text_format: Optional[str] = None,
        notify: bool = True,
        disable_link_preview: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Отправляет сообщение с соблюдением лимита 2 сообщения в секунду.

        Нужно указать ровно один адресат: ``user_id`` или ``chat_id``.
        """
        if (user_id is None) == (chat_id is None):
            raise ValueError("Укажите ровно один адресат: user_id или chat_id")

        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"Текст длиннее {MAX_TEXT_LENGTH} символов ({len(text)}) — MAX отклонит сообщение"
            )

        target = ("user", user_id) if user_id is not None else ("chat", chat_id)
        await self._limiter.acquire(target)

        body: Dict[str, Any] = {"text": text, "notify": notify}
        if attachments:
            body["attachments"] = attachments
        if text_format:
            body["format"] = text_format

        return await self.request(
            "POST",
            "/messages",
            params={
                "user_id": user_id,
                "chat_id": chat_id,
                "disable_link_preview": disable_link_preview,
            },
            json=body,
        )

    async def answer_callback(
        self,
        callback_id: str,
        *,
        notification: Optional[str] = None,
        message: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Ответ на нажатие инлайн-кнопки (событие ``message_callback``)."""
        body: Dict[str, Any] = {}
        if notification:
            body["notification"] = notification
        if message:
            body["message"] = message
        return await self.request("POST", "/answers", params={"callback_id": callback_id}, json=body)

    async def subscribe_webhook(
        self,
        url: str,
        *,
        update_types: Optional[List[str]] = None,
        secret: Optional[str] = None,
    ) -> Any:
        """Подписывает бота на события через вебхук.

        Требования платформы к ``url``: только HTTPS, порт 443 (в адресе не
        указывается), сертификат доверенного центра. Самоподписанные
        сертификаты и HTTP не принимаются.
        """
        if not url.startswith("https://"):
            raise ValueError("URL вебхука должен начинаться с https://")

        body: Dict[str, Any] = {"url": url}
        if update_types:
            body["update_types"] = update_types
        if secret:
            body["secret"] = secret
        return await self.request("POST", "/subscriptions", json=body)

    async def list_subscriptions(self) -> Any:
        """Действующие подписки бота."""
        return await self.request("GET", "/subscriptions")

    async def delete_subscription(self, url: str) -> Any:
        """Отписка от событий по конкретному адресу."""
        return await self.request("DELETE", "/subscriptions", params={"url": url})
