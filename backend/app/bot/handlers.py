"""Обработка событий бота.

Обработчики запускаются уже ПОСЛЕ того, как вебхук ответил 200 OK, и
работают со своей сессией БД: область запроса к этому моменту закрыта.

Исключение внутри обработчика не должно ронять доставку событий, поэтому
диспетчер ловит всё и пишет в лог.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..config import Settings
from ..db.models import BotDialog, utcnow
from ..db.session import get_session_factory
from ..max_api.client import MaxApiClient, MaxApiError
from .keyboards import mini_app_button

logger = logging.getLogger(__name__)

Handler = Callable[["UpdateContext"], Awaitable[None]]
_HANDLERS: Dict[str, Handler] = {}


class UpdateContext:
    """Всё, что нужно обработчику: событие, клиент API и настройки."""

    def __init__(self, update: Dict[str, Any], client: MaxApiClient, settings: Settings) -> None:
        self.update = update
        self.client = client
        self.settings = settings

    @property
    def update_type(self) -> str:
        return str(self.update.get("update_type") or "")

    @property
    def user_id(self) -> Optional[int]:
        """ID пользователя в разных типах событий лежит в разных местах."""
        user = self.update.get("user")
        if isinstance(user, dict) and user.get("user_id") is not None:
            return _as_int(user.get("user_id"))
        if isinstance(user, dict) and user.get("id") is not None:
            return _as_int(user.get("id"))

        message = self.update.get("message")
        if isinstance(message, dict):
            sender = message.get("sender")
            if isinstance(sender, dict):
                return _as_int(sender.get("user_id") or sender.get("id"))

        callback = self.update.get("callback")
        if isinstance(callback, dict):
            sender = callback.get("user")
            if isinstance(sender, dict):
                return _as_int(sender.get("user_id") or sender.get("id"))
        return None

    @property
    def text(self) -> str:
        message = self.update.get("message")
        if isinstance(message, dict):
            body = message.get("body")
            if isinstance(body, dict):
                return str(body.get("text") or "")
        return ""

    @property
    def from_bot(self) -> bool:
        """Сообщение написал бот, а не человек."""
        message = self.update.get("message")
        sender = message.get("sender") if isinstance(message, dict) else None
        return isinstance(sender, dict) and bool(sender.get("is_bot"))

    @property
    def in_dialog(self) -> bool:
        """Сообщение из личного чата с ботом, а не из группы или канала."""
        message = self.update.get("message")
        recipient = message.get("recipient") if isinstance(message, dict) else None
        chat_type = recipient.get("chat_type") if isinstance(recipient, dict) else None
        return chat_type in (None, "", "dialog")


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def handles(update_type: str) -> Callable[[Handler], Handler]:
    """Регистрирует обработчик для типа события."""

    def decorator(func: Handler) -> Handler:
        _HANDLERS[update_type] = func
        return func

    return decorator


async def dispatch(update: Dict[str, Any], client: MaxApiClient, settings: Settings) -> None:
    """Точка входа: выбирает обработчик и выполняет его."""
    context = UpdateContext(update, client, settings)
    handler = _HANDLERS.get(context.update_type)

    if handler is None:
        logger.info("Событие %s без обработчика — пропускаем", context.update_type or "<без типа>")
        return

    try:
        await handler(context)
    except MaxApiError as exc:
        logger.error("Ошибка MAX API при обработке %s: %s", context.update_type, exc)
    except Exception:  # noqa: BLE001 - падение обработчика не должно ломать доставку
        logger.exception("Необработанная ошибка в обработчике %s", context.update_type)


# ---------------------------------------------------------------------
# Работа с состоянием диалога
# ---------------------------------------------------------------------


async def _set_dialog_active(user_id: int, is_active: bool) -> None:
    """Отмечает, может ли бот писать этому пользователю."""
    values: Dict[str, Any] = {"user_id": user_id, "is_active": is_active}
    if not is_active:
        values["stopped_at"] = utcnow()

    statement = (
        pg_insert(BotDialog)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[BotDialog.user_id],
            set_={key: value for key, value in values.items() if key != "user_id"},
        )
    )

    async with get_session_factory()() as session:
        await session.execute(statement)
        await session.commit()


# Метка запуска у кнопки в ответах бота: пользователь пришёл из чата.
MINI_APP_START_PARAM = "bot"

GREETING = (
    "Привет! Это МойОлимп. Я помогу выбрать олимпиады и отследить сроки "
    "их проведения, а так же составлю индивидуальный календарь под "
    "выбранные тобой Олимпиады и буду напоминать о важных датах. "
    "Заходи в мини-приложение!"
)


def _mini_app_button(settings: Settings) -> Optional[Dict[str, Any]]:
    return mini_app_button(settings, MINI_APP_START_PARAM)


# ---------------------------------------------------------------------
# Обработчики событий
# ---------------------------------------------------------------------


@handles("bot_started")
async def on_bot_started(ctx: UpdateContext) -> None:
    """Пользователь впервые запустил бота или возобновил диалог."""
    user_id = ctx.user_id
    if user_id is None:
        logger.warning("bot_started без user_id: %s", ctx.update)
        return

    await _set_dialog_active(user_id, True)

    button = _mini_app_button(ctx.settings)
    await ctx.client.send_message(
        GREETING,
        user_id=user_id,
        attachments=[button] if button else None,
    )


@handles("bot_stopped")
async def on_bot_stopped(ctx: UpdateContext) -> None:
    """Пользователь остановил бота — писать ему больше нельзя."""
    user_id = ctx.user_id
    if user_id is not None:
        await _set_dialog_active(user_id, False)


@handles("dialog_removed")
async def on_dialog_removed(ctx: UpdateContext) -> None:
    """Диалог удалён; приходит вместе с bot_stopped."""
    user_id = ctx.user_id
    if user_id is not None:
        await _set_dialog_active(user_id, False)


@handles("message_created")
async def on_message_created(ctx: UpdateContext) -> None:
    """Сообщение в чате с ботом."""
    user_id = ctx.user_id
    if user_id is None or ctx.from_bot:
        return

    if ctx.in_dialog:
        # Человек пишет боту — значит, и бот может писать ему. bot_started
        # приходит один раз, при первом запуске; кто запустил бота, пока
        # события до сервера не доходили, иначе навсегда остался бы для
        # рассылки «не запустившим».
        await _set_dialog_active(user_id, True)

    button = _mini_app_button(ctx.settings)
    await ctx.client.send_message(
        "Основной сценарий живёт в мини-приложении — откройте его кнопкой ниже."
        if button
        else "Основной сценарий живёт в мини-приложении. Откройте его из настроек бота.",
        user_id=user_id,
        attachments=[button] if button else None,
    )


@handles("message_callback")
async def on_message_callback(ctx: UpdateContext) -> None:
    """Нажатие на инлайн-кнопку.

    На callback нужно ответить, иначе у пользователя останется индикатор
    загрузки на кнопке.
    """
    callback = ctx.update.get("callback")
    if not isinstance(callback, dict):
        return

    callback_id = callback.get("callback_id")
    if not callback_id:
        return

    await ctx.client.answer_callback(str(callback_id), notification="Готово")
