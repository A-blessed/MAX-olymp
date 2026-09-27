"""Утренняя рассылка: кому писать, что и как не написать дважды.

Что написать, решает ``reminders``; здесь — база, отправка и расписание.

Кому. Только тем, кто запустил бота и не остановил его — писать остальным
MAX не разрешит, — не выключил уведомления в мини-приложении и следит хотя
бы за одной олимпиадой. Если сказать нечего, сообщения нет вовсе.

Как не написать дважды. Перед отправкой в журнал вставляется строка
«пользователь + день» со статусом ``sending``; первичный ключ делает эту
вставку замком. Строка уже есть — значит, сегодняшнюю сводку этому
человеку уже отправили: этот же процесс до перезапуска или соседний. Цена
такого порядка — если процесс умрёт ровно между отправкой и отметкой,
строка останется в ``sending``, и повторно в этот день человек сводку не
получит. Из двух ошибок — не прислать или прислать дважды — выбрана первая.

Что делать, если MAX не ответил. Сетевая ошибка, 5xx, 429 и 401 касаются
не человека, а всей рассылки: писать остальным бесполезно. Строку
отпускаем, проход прекращаем, планировщик попробует позже. Остальные 4xx —
например, пользователь удалил диалог — касаются только его: отмечаем
неудачу и идём дальше, повторять её каждую минуту до вечера незачем.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from ..bot.keyboards import mini_app_button
from ..clock import app_timezone
from ..config import Settings
from ..db.models import BotDialog, User
from ..max_api.client import MaxApiClient, MaxApiError
from .models import ReminderLog, ReminderStatus, SavedOlympiad, UserSettings
from .queries import load_plans, load_results, load_saved
from .reminders import ReminderItem, collect_reminders, render_digest
from .rules import locked_stage_ids

logger = logging.getLogger(__name__)

# Метка запуска у кнопки в сводке: пользователь пришёл из напоминания.
REMINDER_START_PARAM = "reminder"

# Позже этого времени рассылку не начинаем, даже если утром бэкенд лежал:
# «что важно сегодня» в одиннадцать вечера — уже не напоминание.
LATEST_START = time(21, 0)

# Как часто планировщик просыпается проверить, не пора ли.
CHECK_INTERVAL_SECONDS = 60

# Пауза после прохода, прерванного недоступностью MAX.
RETRY_AFTER_ABORT = timedelta(minutes=10)


def is_due(now: time, reminder_time: time, latest: time = LATEST_START) -> bool:
    """Пора ли рассылать: время сводки наступило, а вечер ещё нет.

    Если сводку сознательно поставили позже ``latest``, окно тянется до
    полуночи — иначе она не ушла бы никогда.
    """
    upper = latest if reminder_time < latest else time.max
    return reminder_time <= now < upper


@dataclass
class PassStats:
    """Итог одного прохода рассылки."""

    day: date
    recipients: int = 0
    sent: int = 0
    empty: int = 0
    already: int = 0
    failed: int = 0
    aborted: bool = False
    # Для просмотра без отправки: (пользователь, пометка, текст).
    previews: List[Tuple[int, str, str]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "получателей": self.recipients,
            "отправлено": self.sent,
            "сказать нечего": self.empty,
            "уже получили сегодня": self.already,
            "не доставлено": self.failed,
            "прервано": self.aborted,
        }


async def select_recipients(
    session: AsyncSession, *, only_user: Optional[int] = None
) -> List[int]:
    """Кому сегодня вообще можно писать."""
    statement = (
        select(User.id)
        .join(BotDialog, BotDialog.user_id == User.id)
        .outerjoin(UserSettings, UserSettings.user_id == User.id)
        .where(BotDialog.is_active.is_(True))
        # Строки настроек может не быть: она заводится лениво, при первом
        # обращении к ним. По механике уведомления включены по умолчанию.
        .where(
            or_(UserSettings.user_id.is_(None), UserSettings.notifications_enabled.is_(True))
        )
        .where(exists().where(SavedOlympiad.user_id == User.id))
        .order_by(User.id)
    )
    if only_user is not None:
        statement = statement.where(User.id == only_user)
    return list(await session.scalars(statement))


async def why_not_recipient(session: AsyncSession, user_id: int) -> Optional[str]:
    """Почему пользователю не придёт сводка. ``None`` — придёт."""
    if await session.get(User, user_id) is None:
        return "такого пользователя нет: он ни разу не открывал мини-приложение"
    dialog = await session.get(BotDialog, user_id)
    if dialog is None:
        return "бот у него не запущен — писать ему MAX не разрешит"
    if not dialog.is_active:
        return "он остановил бота"
    settings_row = await session.get(UserSettings, user_id)
    if settings_row is not None and not settings_row.notifications_enabled:
        return "уведомления выключены в настройках мини-приложения"
    has_saved = await session.scalar(select(exists().where(SavedOlympiad.user_id == user_id)))
    if not has_saved:
        return "он не следит ни за одной олимпиадой"
    return None


async def build_digest(
    session: AsyncSession, user_id: int, today: date
) -> Tuple[List[ReminderItem], Optional[str]]:
    """Сводка пользователя на день: пункты и готовый текст."""
    rows = await load_saved(session, user_id)
    stage_ids = [stage.id for olympiad, _ in rows for stage in olympiad.stages]
    results = await load_results(session, user_id, stage_ids)
    plans = await load_plans(session, user_id, stage_ids)

    entries = []
    for olympiad, _ in rows:
        locked = locked_stage_ids(olympiad.stages, results)
        for stage in olympiad.stages:
            entries.append((olympiad, stage, results.get(stage.id), stage.id in locked))

    items = collect_reminders(entries, plans, today)
    return items, render_digest(items, today)


async def claim(session: AsyncSession, user_id: int, day: date, *, force: bool = False) -> bool:
    """Занять строку журнала. ``False`` — сводку за этот день уже отправляли."""
    key = [ReminderLog.user_id, ReminderLog.sent_for]
    statement = pg_insert(ReminderLog).values(
        user_id=user_id, sent_for=day, status=ReminderStatus.SENDING.value
    )
    if force:
        statement = statement.on_conflict_do_update(
            index_elements=key,
            set_={"status": ReminderStatus.SENDING.value, "error": None, "updated_at": func.now()},
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=key)
    claimed = await session.scalar(statement.returning(ReminderLog.user_id))
    await session.commit()
    return claimed is not None


async def _finish(
    session: AsyncSession,
    user_id: int,
    day: date,
    status: ReminderStatus,
    *,
    items: int,
    text: Optional[str],
    error: Optional[str] = None,
) -> None:
    await session.execute(
        update(ReminderLog)
        .where(ReminderLog.user_id == user_id, ReminderLog.sent_for == day)
        .values(status=status.value, items=items, text=text, error=error, updated_at=func.now())
    )
    await session.commit()


async def _release(session: AsyncSession, user_id: int, day: date) -> None:
    await session.execute(
        delete(ReminderLog).where(ReminderLog.user_id == user_id, ReminderLog.sent_for == day)
    )
    await session.commit()


def _stops_the_pass(exc: MaxApiError) -> bool:
    """Ошибка про всю рассылку, а не про одного получателя."""
    code = exc.status_code
    return code is None or code in (401, 429) or code >= 500


def _describe(exc: MaxApiError) -> str:
    return f"{exc}; ответ: {exc.payload}" if exc.payload else str(exc)


SessionFactory = Callable[[], Any]


async def schema_problem(session_factory: SessionFactory) -> Optional[str]:
    """Готова ли база к рассылке. ``None`` — готова или судить не о чем.

    Таблица журнала появляется с миграцией. Обновили код, а
    ``alembic upgrade head`` забыли — и без этой проверки планировщик
    каждую минуту выводил бы полотно трейсбека, в котором причина лежит в
    последней строке.
    """
    try:
        async with session_factory() as session:
            await session.execute(select(ReminderLog.user_id).limit(0))
    except ProgrammingError:
        return (
            "в базе нет таблицы reminder_log — не применены миграции. "
            "Выполните «alembic upgrade head» и перезапустите бэкенд"
        )
    except Exception:  # noqa: BLE001 - база недоступна: об этом уже сказала проверка базы
        return None
    return None


async def run_daily_pass(
    session_factory: SessionFactory,
    client: Optional[MaxApiClient],
    settings: Settings,
    today: date,
    *,
    dry_run: bool = False,
    only_user: Optional[int] = None,
    force: bool = False,
) -> PassStats:
    """Один проход рассылки. Повторный запуск за тот же день безопасен."""
    stats = PassStats(day=today)
    async with session_factory() as session:
        recipients = await select_recipients(session, only_user=only_user)
    stats.recipients = len(recipients)

    button = mini_app_button(settings, REMINDER_START_PARAM)

    for user_id in recipients:
        # Своя сессия на каждого: ошибка по одному человеку не должна
        # откатывать отметки о тех, кому уже отправили.
        async with session_factory() as session:
            items, text = await build_digest(session, user_id, today)
            if text is None:
                stats.empty += 1
                continue

            if dry_run:
                logged = await session.get(ReminderLog, (user_id, today))
                note = f"уже в журнале: {logged.status}" if logged else "будет отправлено"
                stats.previews.append((user_id, note, text))
                continue

            if client is None:
                raise RuntimeError("Отправлять нечем: BOT_TOKEN не задан")

            if not await claim(session, user_id, today, force=force):
                stats.already += 1
                continue

            try:
                await client.send_message(
                    text, user_id=user_id, attachments=[button] if button else None
                )
            except MaxApiError as exc:
                if _stops_the_pass(exc):
                    await _release(session, user_id, today)
                    stats.aborted = True
                    logger.error("Рассылка прервана, MAX не принимает сообщения: %s", exc)
                    break
                await _finish(
                    session, user_id, today, ReminderStatus.FAILED,
                    items=len(items), text=text, error=_describe(exc),
                )
                stats.failed += 1
                logger.warning("Сводка пользователю %s не доставлена: %s", user_id, exc)
                continue
            except Exception as exc:  # noqa: BLE001 - один получатель не должен ронять рассылку
                await _finish(
                    session, user_id, today, ReminderStatus.FAILED,
                    items=len(items), text=text, error=repr(exc),
                )
                stats.failed += 1
                logger.exception("Сводка пользователю %s не доставлена", user_id)
                continue

            await _finish(
                session, user_id, today, ReminderStatus.SENT, items=len(items), text=text
            )
            stats.sent += 1

    if not dry_run:
        logger.info("Утренняя сводка за %s: %s", today, stats.as_dict())
    return stats


PassRunner = Callable[..., Awaitable[PassStats]]


class ReminderScheduler:
    """Раз в день, в заданное время, запускает рассылку.

    Живёт внутри процесса бэкенда: отдельная служба — это ещё одна вещь,
    которую надо настроить на сервере и не забыть поднять. Сколько бы раз
    процесс ни перезапускали, лишнего не уйдёт: что отправлено, помнит
    журнал, а не память процесса.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        client: MaxApiClient,
        settings: Settings,
        *,
        now: Optional[Callable[[], datetime]] = None,
        run: PassRunner = run_daily_pass,
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._settings = settings
        self._now = now or (lambda: datetime.now(app_timezone()))
        self._run = run
        self._done_for: Optional[date] = None
        self._not_before: Optional[datetime] = None
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="morning-reminders")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        last_error: Optional[str] = None
        while True:
            try:
                await self.tick()
                last_error = None
            except Exception as exc:  # noqa: BLE001 - планировщик не должен умирать от одной ошибки
                # Трейсбек — один раз на новую ошибку. Та же ошибка каждую
                # минуту до вечера похоронила бы под собой весь остальной лог.
                signature = f"{type(exc).__name__}: {exc}"
                if signature != last_error:
                    logger.exception("Планировщик напоминаний: ошибка, пробуем раз в минуту")
                    last_error = signature
                else:
                    logger.warning("Планировщик напоминаний: всё та же %s", type(exc).__name__)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def tick(self) -> Optional[PassStats]:
        """Одна проверка: пора ли, и если пора — рассылка."""
        now = self._now()
        today = now.date()
        if self._done_for == today:
            return None
        if self._not_before is not None and now < self._not_before:
            return None
        if not is_due(now.time(), self._settings.reminder_time):
            return None

        stats = await self._run(self._session_factory, self._client, self._settings, today)
        if stats.aborted:
            self._not_before = now + RETRY_AFTER_ABORT
        else:
            self._done_for = today
            self._not_before = None
        return stats
