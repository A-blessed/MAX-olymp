"""Тесты бота: кого он запоминает как собеседника и видит ли его MAX.

Без подписки на события и без записи в bot_dialogs утренняя сводка не
уходит никому, а снаружи всё выглядит рабочим. Здесь проверяется, что
бэкенд замечает оба случая сам.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import pytest

from app.bot import handlers
from app.bot.subscription import (
    SETUP_COMMAND,
    UPDATE_TYPES,
    describe,
    log_subscription,
    parse_subscriptions,
)
from app.config import Settings
from app.max_api.client import MaxApiError

URL = "https://my-olymp.ru/webhook"
OLD = "https://abc123.ngrok-free.app/webhook"


def settings() -> Settings:
    return Settings(public_base_url="https://my-olymp.ru", bot_username="olymp_bot")


class FakeClient:
    def __init__(self, subscriptions: Any = None, error: Exception = None) -> None:
        self.subscriptions = subscriptions
        self.error = error
        self.sent: List[Dict[str, Any]] = []

    async def list_subscriptions(self) -> Any:
        if self.error:
            raise self.error
        return self.subscriptions

    async def send_message(self, text: str, **kwargs: Any) -> Dict[str, Any]:
        self.sent.append({"text": text, **kwargs})
        return {}


# ---------------------------------------------------------------------
# Подписка на события
# ---------------------------------------------------------------------


class TestParseSubscriptions:
    def test_our_subscription_with_all_events(self):
        state = parse_subscriptions(
            {"subscriptions": [{"url": URL, "update_types": list(UPDATE_TYPES)}]}, URL
        )
        assert state.subscribed
        assert state.missing_types == []
        assert state.others == []

    def test_url_compared_without_trailing_slash_and_case(self):
        state = parse_subscriptions({"subscriptions": [{"url": "https://MY-OLYMP.ru/webhook/"}]}, URL)
        assert state.subscribed

    def test_no_update_types_means_all_events(self):
        for types in (None, []):
            state = parse_subscriptions({"subscriptions": [{"url": URL, "update_types": types}]}, URL)
            assert state.missing_types == []

    def test_missing_events_are_named(self):
        state = parse_subscriptions(
            {"subscriptions": [{"url": URL, "update_types": ["message_created"]}]}, URL
        )
        assert state.subscribed
        assert "bot_started" in state.missing_types
        assert "message_created" not in state.missing_types

    def test_only_old_tunnel(self):
        state = parse_subscriptions({"subscriptions": [{"url": OLD}]}, URL)
        assert not state.subscribed
        assert state.others == [OLD]

    @pytest.mark.parametrize(
        "payload",
        [None, {}, [], {"subscriptions": None}, {"subscriptions": [{"url": None}, "мусор"]}],
    )
    def test_odd_payloads_mean_no_subscription(self, payload):
        state = parse_subscriptions(payload, URL)
        assert not state.subscribed
        assert state.others == []

    def test_describe_tells_what_to_run(self):
        missing = describe(parse_subscriptions({"subscriptions": [{"url": OLD}]}, URL))
        assert URL in missing[0] and SETUP_COMMAND in missing[0]
        assert f"--delete --url {OLD}" in missing[1]

        ok = describe(parse_subscriptions({"subscriptions": [{"url": URL}]}, URL))
        assert ok == [f"Подписка на события MAX: {URL}"]


class TestLogSubscription:
    async def test_no_subscription_is_an_error(self, caplog):
        with caplog.at_level(logging.INFO, logger="app.bot.subscription"):
            await log_subscription(FakeClient({"subscriptions": []}), settings())
        assert [r.levelno for r in caplog.records] == [logging.ERROR]
        assert SETUP_COMMAND in caplog.records[0].getMessage()

    async def test_subscription_in_place(self, caplog):
        with caplog.at_level(logging.INFO, logger="app.bot.subscription"):
            await log_subscription(FakeClient({"subscriptions": [{"url": URL}]}), settings())
        assert [r.levelno for r in caplog.records] == [logging.INFO]

    async def test_max_unreachable_does_not_raise(self, caplog):
        client = FakeClient(error=MaxApiError("Не удалось подключиться"))
        with caplog.at_level(logging.INFO, logger="app.bot.subscription"):
            await log_subscription(client, settings())
        assert [r.levelno for r in caplog.records] == [logging.WARNING]


# ---------------------------------------------------------------------
# Кого бот запоминает
# ---------------------------------------------------------------------


def message(sender_id: int = 42, *, chat_type: str = "dialog", is_bot: bool = False) -> Dict[str, Any]:
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": sender_id, "is_bot": is_bot},
            "recipient": {"chat_id": 1000, "chat_type": chat_type},
            "body": {"text": "привет"},
        },
    }


@pytest.fixture
def dialogs(monkeypatch) -> List[tuple]:
    calls: List[tuple] = []

    async def record(user_id: int, is_active: bool) -> None:
        calls.append((user_id, is_active))

    monkeypatch.setattr(handlers, "_set_dialog_active", record)
    return calls


class TestMessageCreated:
    async def test_message_in_dialog_marks_bot_as_started(self, dialogs):
        client = FakeClient()
        await handlers.dispatch(message(42), client, settings())
        assert dialogs == [(42, True)]
        assert [m["user_id"] for m in client.sent] == [42]

    async def test_group_chat_does_not_count(self, dialogs):
        await handlers.dispatch(message(42, chat_type="chat"), FakeClient(), settings())
        assert dialogs == []

    async def test_own_messages_are_ignored(self, dialogs):
        client = FakeClient()
        await handlers.dispatch(message(7, is_bot=True), client, settings())
        assert dialogs == []
        assert client.sent == []

    async def test_bot_started_greets_with_button(self, dialogs):
        client = FakeClient()
        await handlers.dispatch({"update_type": "bot_started", "user": {"user_id": 42}}, client, settings())
        assert dialogs == [(42, True)]
        assert client.sent[0]["text"] == handlers.GREETING
        assert client.sent[0]["attachments"]
