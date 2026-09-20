"""Валидация данных запуска мини-приложения MAX (WebAppData).

Это ядро бэкенда мини-приложения. MAX подписывает параметры запуска
HMAC-SHA256 на основе токена бота. Поскольку токен есть только у сервера,
проверить подпись может только сервер — поэтому мини-приложению вообще
нужен бэкенд.

Алгоритм: https://dev.max.ru/docs/webapps/validation

Модуль намеренно написан на чистой стандартной библиотеке, без FastAPI,
pydantic и настроек — чтобы его можно было тестировать изолированно.
"""

from __future__ import annotations

import hmac
import json
import time
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

# Ключ, которым подписывается токен бота при выводе secret_key.
# Это фиксированная строка из документации, а не наш секрет.
SECRET_KEY_SALT = b"WebAppData"

# Имя параметра во фрагменте URL, в котором лежат подписанные данные.
WEB_APP_DATA_PARAM = "WebAppData"


class LaunchDataError(Exception):
    """Базовая ошибка валидации данных запуска."""

    code = "invalid_launch_data"


class MalformedLaunchData(LaunchDataError):
    """Строку не удалось разобрать на пары key=value."""

    code = "malformed"


class NotUrlDecoded(LaunchDataError):
    """Строка пришла ещё раз URL-закодированной.

    Частая ошибка стыковки с фронтендом: во фрагменте URL значение
    ``WebAppData`` закодировано, и его нужно декодировать ровно один раз
    перед передачей на бэкенд.
    """

    code = "not_url_decoded"


class DuplicateParameter(LaunchDataError):
    """Параметр встречается больше одного раза — вектор подмены значения."""

    code = "duplicate_parameter"


class MissingHash(LaunchDataError):
    """В данных нет параметра hash — проверять нечего."""

    code = "missing_hash"


class BadSignature(LaunchDataError):
    """Подпись не совпала: данные подделаны или токен бота не тот."""

    code = "bad_signature"


class LaunchDataExpired(LaunchDataError):
    """auth_date слишком старый — строку запуска могли перехватить."""

    code = "expired"


@dataclass(frozen=True)
class MaxUser:
    """Пользователь MAX из проверенных данных запуска.

    Единственный доверенный источник идентификатора пользователя.
    Никогда не берите user_id из тела запроса — его подделает кто угодно.
    """

    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None
    photo_url: Optional[str] = None

    @property
    def full_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or f"user{self.id}"


@dataclass(frozen=True)
class LaunchData:
    """Результат успешной валидации."""

    user: MaxUser
    auth_date: int
    chat: Optional[dict] = None
    query_id: Optional[str] = None
    start_param: Optional[str] = None
    ip: Optional[str] = None
    raw: Dict[str, str] = field(default_factory=dict)

    @property
    def age_seconds(self) -> int:
        return max(0, int(time.time()) - self.auth_date)


def extract_web_app_data(url: str) -> str:
    """Достаёт значение WebAppData из фрагмента URL (часть после ``#``).

    Нужно в основном для отладки и тестов: в бою фронтенд присылает уже
    извлечённую строку (``window.WebApp.initData``).
    """
    fragment = urlparse(url).fragment
    if not fragment:
        raise MalformedLaunchData("В URL нет фрагмента после '#'")

    found: List[str] = []
    for chunk in fragment.split("&"):
        key, sep, value = chunk.partition("=")
        if sep and key == WEB_APP_DATA_PARAM:
            found.append(value)

    if not found:
        raise MalformedLaunchData(f"Во фрагменте URL нет параметра {WEB_APP_DATA_PARAM}")
    if len(found) > 1:
        raise DuplicateParameter(f"{WEB_APP_DATA_PARAM} встречается более одного раза")

    # Значение внутри фрагмента закодировано ровно один раз — снимаем этот слой.
    return unquote(found[0])


def _split_pairs(raw: str) -> List[Tuple[str, str]]:
    """Разбивает ``key1=value1&key2=value2`` на список пар.

    Значения на этом шаге НЕ декодируются — они ещё закодированы, и
    декодирование произойдёт позже, строго по алгоритму из документации.
    """
    if not raw or not raw.strip():
        raise MalformedLaunchData("Пустая строка данных запуска")

    if "hash=" not in raw and "hash%3D" in raw.replace("%3d", "%3D"):
        raise NotUrlDecoded(
            "Похоже, строка ещё URL-закодирована: найдено 'hash%3D' вместо 'hash='. "
            "Декодируйте значение WebAppData ровно один раз перед отправкой на бэкенд."
        )

    pairs: List[Tuple[str, str]] = []
    for chunk in raw.split("&"):
        if not chunk:
            continue
        key, sep, value = chunk.partition("=")
        if not sep:
            raise MalformedLaunchData(f"Фрагмент {chunk!r} не является парой key=value")
        pairs.append((key, value))

    if not pairs:
        raise MalformedLaunchData("Не удалось разобрать ни одной пары key=value")
    return pairs


def compute_secret_key(bot_token: str) -> bytes:
    """secret_key = HMAC-SHA256(key="WebAppData", msg=BOT_TOKEN).

    Обратите внимание на порядок аргументов: ключом выступает строка
    ``WebAppData``, а сообщением — токен бота, а не наоборот.
    """
    return hmac.new(SECRET_KEY_SALT, bot_token.encode("utf-8"), sha256).digest()


def build_launch_params(pairs: List[Tuple[str, str]]) -> str:
    """Собирает каноническую строку для подписи.

    Ожидает пары с уже декодированными значениями и без ``hash``.
    """
    ordered = sorted(pairs, key=lambda item: item[0])
    return "\n".join(f"{key}={value}" for key, value in ordered)


def sign(bot_token: str, launch_params: str) -> str:
    """hex(HMAC-SHA256(secret_key, launch_params))."""
    secret_key = compute_secret_key(bot_token)
    return hmac.new(secret_key, launch_params.encode("utf-8"), sha256).hexdigest()


def _parse_user(raw_user: str) -> MaxUser:
    try:
        payload = json.loads(raw_user)
    except (TypeError, ValueError) as exc:
        raise MalformedLaunchData(f"Параметр user не является корректным JSON: {exc}") from exc

    if not isinstance(payload, dict) or "id" not in payload:
        raise MalformedLaunchData("В параметре user нет поля id")

    try:
        user_id = int(payload["id"])
    except (TypeError, ValueError) as exc:
        raise MalformedLaunchData("Поле user.id не является числом") from exc

    return MaxUser(
        id=user_id,
        first_name=payload.get("first_name"),
        last_name=payload.get("last_name"),
        username=payload.get("username"),
        language_code=payload.get("language_code"),
        photo_url=payload.get("photo_url"),
    )


def validate(raw: str, bot_token: str, ttl_seconds: Optional[int] = 86400) -> LaunchData:
    """Проверяет подпись данных запуска и возвращает доверенные данные.

    :param raw: значение ``WebAppData``, декодированное ровно один раз
        (то, что фронтенд получает из ``window.WebApp.initData``).
    :param bot_token: токен бота из переменной окружения.
    :param ttl_seconds: максимальный возраст ``auth_date``. ``None`` отключает
        проверку — так делать не стоит: без неё перехваченная строка запуска
        работает бессрочно.
    :raises LaunchDataError: при любой неуспешной проверке.
    """
    if not bot_token:
        raise LaunchDataError("Не задан токен бота — проверка подписи невозможна")

    pairs = _split_pairs(raw)

    # Шаг 1. Каждый параметр должен встречаться ровно один раз.
    # Дубликат ключа позволяет подсунуть второе значение, которое не попадёт
    # в подписываемую строку, но будет прочитано приложением.
    seen: Dict[str, int] = {}
    for key, _ in pairs:
        seen[key] = seen.get(key, 0) + 1
    duplicates = sorted(key for key, count in seen.items() if count > 1)
    if duplicates:
        raise DuplicateParameter(f"Параметры встречаются более одного раза: {', '.join(duplicates)}")

    # Шаг 2. Забираем hash и исключаем его из подписываемых данных.
    if "hash" not in seen:
        raise MissingHash("В данных запуска нет параметра hash")

    original_hash = ""
    signed_pairs: List[Tuple[str, str]] = []
    for key, value in pairs:
        if key == "hash":
            original_hash = unquote(value)
            continue
        # Шаг 3. URL-декодирование значений.
        signed_pairs.append((key, unquote(value)))

    if not signed_pairs:
        raise MalformedLaunchData("Кроме hash в данных запуска нет ни одного параметра")

    # Шаги 4-6. Сортировка по ключу a→z, склейка через \n, подпись.
    launch_params = build_launch_params(signed_pairs)
    expected_hash = sign(bot_token, launch_params)

    # Шаг 7. Сравнение в постоянном времени, чтобы не сливать подпись по таймингу.
    if not hmac.compare_digest(expected_hash, original_hash):
        raise BadSignature("Подпись данных запуска не совпала")

    values = dict(signed_pairs)

    raw_auth_date = values.get("auth_date")
    if raw_auth_date is None:
        raise MalformedLaunchData("В данных запуска нет auth_date")
    try:
        auth_date = int(raw_auth_date)
    except (TypeError, ValueError) as exc:
        raise MalformedLaunchData("auth_date не является числом") from exc

    if ttl_seconds is not None:
        age = int(time.time()) - auth_date
        if age > ttl_seconds:
            raise LaunchDataExpired(
                f"Данные запуска устарели: возраст {age} с при лимите {ttl_seconds} с"
            )

    raw_user = values.get("user")
    if not raw_user:
        raise MalformedLaunchData("В данных запуска нет параметра user")

    chat = None
    if values.get("chat"):
        try:
            chat = json.loads(values["chat"])
        except ValueError:
            # Чат — вспомогательная информация; подпись уже проверена,
            # поэтому битый JSON здесь не повод отклонять запрос целиком.
            chat = None

    return LaunchData(
        user=_parse_user(raw_user),
        auth_date=auth_date,
        chat=chat,
        query_id=values.get("query_id"),
        start_param=values.get("start_param"),
        ip=values.get("ip"),
        raw=values,
    )
