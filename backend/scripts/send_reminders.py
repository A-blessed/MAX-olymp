"""Утренние напоминания вручную: посмотреть, проверить на себе, разослать.

    python -m scripts.send_reminders --users
    python -m scripts.send_reminders --dry-run
    python -m scripts.send_reminders --dry-run --date 2026-10-14
    python -m scripts.send_reminders --user 123456789
    python -m scripts.send_reminders --user 123456789 --date 2026-10-14 --force

Бэкенд рассылает сводку сам, каждый день в REMINDER_TIME. Скрипт нужен,
чтобы увидеть её заранее и проверить доставку на себе, не дожидаясь утра.

``--users`` — все, кто открывал мини-приложение: так находится свой id.
``--dry-run`` — показать тексты, ничего не отправляя и не отмечая.
``--date`` — считать сводку так, будто сегодня этот день.
``--force`` — отправить, даже если за этот день уже отправляли.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from sqlalchemy import func, select

from app.clock import today as app_today
from app.config import get_settings
from app.db.models import BotDialog, User
from app.db.session import dispose_engine, get_session_factory
from app.max_api.client import MaxApiClient
from app.personal.models import SavedOlympiad, UserSettings
from app.personal.reminder_service import build_digest, run_daily_pass, why_not_recipient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Утренние напоминания вручную")
    parser.add_argument("--users", action="store_true", help="список пользователей и их id")
    parser.add_argument("--dry-run", action="store_true", help="только показать, не отправлять")
    parser.add_argument("--user", type=int, help="только этому пользователю")
    parser.add_argument("--date", type=date.fromisoformat, help="день сводки, ГГГГ-ММ-ДД")
    parser.add_argument("--force", action="store_true", help="повторно, даже если уже отправляли")
    return parser


async def list_users() -> None:
    saved = (
        select(SavedOlympiad.user_id, func.count().label("saved"))
        .group_by(SavedOlympiad.user_id)
        .subquery()
    )
    statement = (
        select(User, BotDialog.is_active, UserSettings.notifications_enabled, saved.c.saved)
        .outerjoin(BotDialog, BotDialog.user_id == User.id)
        .outerjoin(UserSettings, UserSettings.user_id == User.id)
        .outerjoin(saved, saved.c.user_id == User.id)
        .order_by(User.last_seen_at.desc())
    )
    async with get_session_factory()() as session:
        rows = (await session.execute(statement)).all()

    if not rows:
        print("Пользователей нет: мини-приложение ещё никто не открывал.")
        return

    # «нет событий» — не то же, что «не запущен»: сервер просто ничего не
    # слышал от этого человека. Запуск, остановка и любое сообщение боту
    # приходят событием MAX, и без подписки на события не приходит ничего.
    print(f"{'id':>12}  {'бот':<11} {'увед.':<6} {'олимп.':>6}  имя")
    for user, dialog_active, notifications, saved_count in rows:
        bot = "нет событий" if dialog_active is None else ("запущен" if dialog_active else "остановлен")
        notify = "выкл" if notifications is False else "вкл"
        name = " ".join(filter(None, [user.first_name, user.last_name])) or "—"
        if user.username:
            name += f" (@{user.username})"
        print(f"{user.id:>12}  {bot:<11} {notify:<6} {saved_count or 0:>6}  {name}")

    if all(dialog_active is None for _, dialog_active, _, _ in rows):
        print(
            "\nНи от кого не пришло ни одного события бота — похоже, MAX не присылает "
            "их серверу. Проверьте подписку: python -m scripts.setup_webhook --list"
        )


async def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()

    if args.users:
        try:
            await list_users()
        finally:
            await dispose_engine()
        return 0

    if args.date and not args.dry_run and args.user is None:
        # Разослать всем сводку за чужой день — верный способ напугать
        # людей «последним днём», который давно прошёл.
        print("--date без --dry-run допустим только вместе с --user")
        return 1

    day = args.date or app_today()

    # Сначала — придёт ли сводка вообще. Для этого нужна только база, и
    # «уведомления выключены» полезнее услышать раньше, чем «нет токена».
    if args.user is not None:
        preview = None
        try:
            async with get_session_factory()() as session:
                reason = await why_not_recipient(session, args.user)
                if reason and args.dry_run:
                    # Текст сводки от причины не зависит — посмотреть его можно.
                    _, preview = await build_digest(session, args.user, day)
        except Exception:
            await dispose_engine()
            raise
        if reason:
            await dispose_engine()
            print(f"Пользователю {args.user} сводка не придёт: {reason}.")
            if args.dry_run:
                print(f"\nКогда это исправят, за {day.isoformat()} он получил бы:\n")
                print(preview or "ничего: на этот день сказать нечего.")
            return 1

    client = None
    if not args.dry_run:
        if not settings.bot_token:
            print("BOT_TOKEN не задан — отправлять нечем. Посмотреть можно с --dry-run.")
            return 1
        client = MaxApiClient(
            token=settings.bot_token,
            base_url=settings.max_api_base_url,
            timeout=settings.max_api_timeout,
            extra_ca_files=settings.extra_ca_files(),
        )

    try:
        stats = await run_daily_pass(
            get_session_factory(),
            client,
            settings,
            day,
            dry_run=args.dry_run,
            only_user=args.user,
            force=args.force,
        )
    finally:
        if client is not None:
            await client.aclose()
        await dispose_engine()

    for user_id, note, text in stats.previews:
        print(f"===== {user_id} — {note} =====")
        print(text)
        print()

    mode = " (просмотр — ничего не отправлялось)" if args.dry_run else ""
    print(f"Сводка за {day.isoformat()}{mode}:")
    for title, value in stats.as_dict().items():
        print(f"  {title}: {value}")

    if stats.empty and args.user is not None and not stats.previews and not stats.sent:
        print(
            "\nНа этот день сказать нечего: ни начала, ни последнего дня, ни плана. "
            "Попробуйте --date с днём, когда у его олимпиад есть события."
        )
    return 1 if stats.aborted else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
