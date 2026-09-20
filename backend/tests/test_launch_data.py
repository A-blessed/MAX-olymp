"""Тесты валидации данных запуска.

Набор случаев закрывает то, ради чего проверка вообще существует:
валидные данные, подделанный идентификатор, чужой токен, просроченный
auth_date и дубликат параметра.
"""

from __future__ import annotations

import hmac
import json
import time
from hashlib import sha256

import pytest

from app.security import launch_data as launch
from app.security.testing import build_signed_launch_data

TOKEN = "test-token-abcdef0123456789"
OTHER_TOKEN = "another-token-9876543210"


# ---------------------------------------------------------------------
# Валидные данные
# ---------------------------------------------------------------------


def test_valid_launch_data_passes():
    raw = build_signed_launch_data(TOKEN, user_id=42, first_name="Аня")

    data = launch.validate(raw, TOKEN)

    assert data.user.id == 42
    assert data.user.first_name == "Аня"
    assert data.auth_date <= int(time.time())


def test_start_param_is_extracted():
    raw = build_signed_launch_data(TOKEN, start_param="promo_2026")

    data = launch.validate(raw, TOKEN)

    assert data.start_param == "promo_2026"


def test_chat_is_parsed():
    raw = build_signed_launch_data(TOKEN, chat={"id": 777, "type": "DIALOG"})

    data = launch.validate(raw, TOKEN)

    assert data.chat == {"id": 777, "type": "DIALOG"}


def test_cyrillic_values_survive_encoding_roundtrip():
    """Кириллица кодируется в строке запуска и должна разворачиваться обратно."""
    raw = build_signed_launch_data(TOKEN, first_name="Пётр", last_name="Ильич")

    data = launch.validate(raw, TOKEN)

    assert data.user.first_name == "Пётр"
    assert data.user.full_name == "Пётр Ильич"


# ---------------------------------------------------------------------
# Подделка данных
# ---------------------------------------------------------------------


def test_tampered_user_id_is_rejected():
    """Главный сценарий атаки: подменить id пользователя, оставив старую подпись."""
    raw = build_signed_launch_data(TOKEN, user_id=987654321)
    # Значение достаточно приметное, чтобы не совпасть с auth_date или query_id.
    tampered = raw.replace("987654321", "987654322")
    assert tampered != raw

    with pytest.raises(launch.BadSignature):
        launch.validate(tampered, TOKEN)


def test_foreign_token_is_rejected():
    """Строка, подписанная чужим ботом, не должна проходить у нас."""
    raw = build_signed_launch_data(OTHER_TOKEN)

    with pytest.raises(launch.BadSignature):
        launch.validate(raw, TOKEN)


def test_duplicate_parameter_is_rejected():
    """Дубликат ключа позволяет подсунуть значение мимо подписи."""
    raw = build_signed_launch_data(TOKEN, user_id=500)
    forged_user = json.dumps({"id": 501, "first_name": "Злоумышленник"}, ensure_ascii=False)
    duplicated = f"{raw}&user={forged_user}"

    with pytest.raises(launch.DuplicateParameter):
        launch.validate(duplicated, TOKEN)


def test_duplicate_hash_is_rejected():
    raw = build_signed_launch_data(TOKEN)

    with pytest.raises(launch.DuplicateParameter):
        launch.validate(f"{raw}&hash=deadbeef", TOKEN)


def test_missing_hash_is_rejected():
    raw = build_signed_launch_data(TOKEN)
    without_hash = raw.split("&hash=")[0]

    with pytest.raises(launch.MissingHash):
        launch.validate(without_hash, TOKEN)


def test_empty_hash_is_rejected():
    raw = build_signed_launch_data(TOKEN)
    without_hash = raw.split("&hash=")[0]

    with pytest.raises(launch.BadSignature):
        launch.validate(f"{without_hash}&hash=", TOKEN)


# ---------------------------------------------------------------------
# Срок годности
# ---------------------------------------------------------------------


def test_expired_auth_date_is_rejected():
    """Без этой проверки перехваченная строка работает бессрочно."""
    raw = build_signed_launch_data(TOKEN, auth_date=int(time.time()) - 7200)

    with pytest.raises(launch.LaunchDataExpired):
        launch.validate(raw, TOKEN, ttl_seconds=3600)


def test_expiry_can_be_disabled_explicitly():
    raw = build_signed_launch_data(TOKEN, auth_date=int(time.time()) - 7200)

    data = launch.validate(raw, TOKEN, ttl_seconds=None)

    assert data.age_seconds >= 7200


def test_fresh_data_passes_ttl():
    raw = build_signed_launch_data(TOKEN, auth_date=int(time.time()) - 10)

    data = launch.validate(raw, TOKEN, ttl_seconds=3600)

    assert data.age_seconds < 3600


# ---------------------------------------------------------------------
# Битый ввод
# ---------------------------------------------------------------------


def test_empty_string_is_rejected():
    with pytest.raises(launch.MalformedLaunchData):
        launch.validate("", TOKEN)


def test_still_encoded_string_gives_a_clear_error():
    """Типовая ошибка стыковки: фронтенд не декодировал WebAppData."""
    with pytest.raises(launch.NotUrlDecoded):
        launch.validate("auth_date%3D123%26hash%3Ddeadbeef", TOKEN)


def test_missing_bot_token_is_rejected():
    raw = build_signed_launch_data(TOKEN)

    with pytest.raises(launch.LaunchDataError):
        launch.validate(raw, "")


def test_chunk_without_equals_sign_is_rejected():
    with pytest.raises(launch.MalformedLaunchData):
        launch.validate("auth_date=1&brokenchunk&hash=x", TOKEN)


def test_user_without_id_is_rejected():
    raw = build_signed_launch_data(TOKEN, extra={"user": json.dumps({"first_name": "Без id"})})

    with pytest.raises(launch.MalformedLaunchData):
        launch.validate(raw, TOKEN)


# ---------------------------------------------------------------------
# Соответствие алгоритму из документации
# ---------------------------------------------------------------------


def test_secret_key_matches_documented_formula():
    """secret_key = HMAC-SHA256(key="WebAppData", msg=BOT_TOKEN).

    Порядок аргументов здесь путают чаще всего: ключ — строка WebAppData,
    сообщение — токен бота.
    """
    expected = hmac.new(b"WebAppData", TOKEN.encode(), sha256).digest()

    assert launch.compute_secret_key(TOKEN) == expected


def test_launch_params_are_sorted_and_newline_joined():
    pairs = [("user", "{}"), ("auth_date", "1771409719"), ("ip", "192.168.0.1")]

    result = launch.build_launch_params(pairs)

    assert result == 'auth_date=1771409719\nip=192.168.0.1\nuser={}'


def test_matches_documented_example():
    """Сверка с примером из dev.max.ru/docs/webapps/validation.

    Документация приводит URL запуска и строку launch_params, которая из
    него должна получиться. Подпись в примере заменена плейсхолдером,
    поэтому проверяем то, что проверить можно: разбор фрагмента, снятие
    двух слоёв URL-кодирования, сортировку и склейку через \\n.

    Именно на этих шагах расходятся реализации: один лишний или
    недостающий вызов decode — и подпись не сойдётся никогда.
    """
    from urllib.parse import unquote

    url = (
        "https://example.com#WebAppData="
        "chat%3D%257B%2522id%2522%253A12345%252C%2522type%2522%253A%2522DIALOG%2522%257D"
        "%26ip%3D192.168.0.1"
        "%26user%3D%257B%2522id%2522%253A67890%252C%2522first_name%2522%253A%2522Max%2522"
        "%252C%2522last_name%2522%253A%2522User%2522%252C%2522username%2522%253Anull"
        "%252C%2522language_code%2522%253A%2522ru%2522%252C%2522photo_url%2522%253Anull%257D"
        "%26query_id%3D4c0ab423-342b-4e45-aea4-2747dbc500cd"
        "%26auth_date%3D1771409719"
        "%26hash%3Ddeadbeef"
        "&WebAppPlatform=web&WebAppVersion=26.2.8"
    )
    expected = (
        'auth_date=1771409719\n'
        'chat={"id":12345,"type":"DIALOG"}\n'
        'ip=192.168.0.1\n'
        'query_id=4c0ab423-342b-4e45-aea4-2747dbc500cd\n'
        'user={"id":67890,"first_name":"Max","last_name":"User","username":null,'
        '"language_code":"ru","photo_url":null}'
    )

    raw = launch.extract_web_app_data(url)
    pairs = [(key, unquote(value)) for key, value in launch._split_pairs(raw) if key != "hash"]

    assert launch.build_launch_params(pairs) == expected


def test_extract_web_app_data_from_url_fragment():
    raw = build_signed_launch_data(TOKEN, user_id=99)
    from urllib.parse import quote

    url = f"https://example.com#WebAppData={quote(raw, safe='')}&WebAppPlatform=web"

    extracted = launch.extract_web_app_data(url)

    assert launch.validate(extracted, TOKEN).user.id == 99
