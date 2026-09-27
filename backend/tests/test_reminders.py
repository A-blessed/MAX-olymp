"""Тесты утренних напоминаний: что попадает в сводку и когда она уходит.

Расчёт и расписание — чистые функции, поэтому проверяются без базы и без
сети. Доставка и журнал проверяются отдельно, на настоящем Postgres.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from app.catalog.dates import Precision
from app.catalog.models import Olympiad, Stage, StageKind, Subject
from app.max_api.client import MAX_TEXT_LENGTH
from app.personal.models import StageResult
from app.personal.reminder_service import (
    LATEST_START,
    RETRY_AFTER_ABORT,
    PassStats,
    ReminderScheduler,
    is_due,
)
from app.personal.reminders import (
    DEADLINE_HEADS_UP_DAYS,
    MAX_ITEMS,
    ReminderKind,
    Section,
    collect_reminders,
    reminder_for,
    render_digest,
)

TODAY = date(2026, 10, 14)
DAY = Precision.DAY
MONTH = Precision.MONTH


def stage(
    stage_id=1,
    starts_on=None,
    start_precision=None,
    ends_on=None,
    end_precision=None,
    kind=StageKind.QUALIFYING,
    name="Отборочный этап",
) -> Stage:
    return Stage(
        id=stage_id,
        position=0,
        external_key=f"k{stage_id}",
        name=name,
        kind=kind,
        starts_on=starts_on,
        start_precision=start_precision,
        ends_on=ends_on,
        end_precision=end_precision,
    )


def olympiad(name="Высшая проба", subject="Математика") -> Olympiad:
    o = Olympiad(id=10, name=name, source_url="https://example/o/")
    o.subject = Subject(id=1, slug="math", name=subject) if subject else None
    return o


def single_day(day, **kw):
    return stage(starts_on=day, start_precision=DAY, **kw)


def range_(start, end, **kw):
    return stage(starts_on=start, start_precision=DAY, ends_on=end, end_precision=DAY, **kw)


def deadline(day, **kw):
    return stage(ends_on=day, end_precision=DAY, **kw)


def kind_of(s, *, result=None, locked=False, planned_on=None, today=TODAY):
    item = reminder_for(
        s, olympiad(), result=result, locked=locked, planned_on=planned_on, today=today
    )
    return item.kind if item else None


d = lambda days: TODAY + timedelta(days=days)  # noqa: E731


class TestWhatToRemind:
    def test_starts_today(self):
        assert kind_of(single_day(TODAY)) is ReminderKind.STARTS_TODAY

    def test_starts_tomorrow(self):
        assert kind_of(single_day(d(1))) is ReminderKind.STARTS_TOMORROW

    def test_last_day_of_a_running_range(self):
        assert kind_of(range_(d(-5), TODAY)) is ReminderKind.ENDS_TODAY

    def test_last_day_tomorrow(self):
        assert kind_of(range_(d(-5), d(1))) is ReminderKind.ENDS_TOMORROW

    def test_heads_up_before_the_end(self):
        assert kind_of(range_(d(-5), d(DEADLINE_HEADS_UP_DAYS))) is ReminderKind.ENDS_SOON

    def test_deadline_without_start_is_reminded(self):
        """«Приём работ до 17-го»: начала нет, а напоминать надо."""
        assert kind_of(deadline(TODAY)) is ReminderKind.ENDS_TODAY
        assert kind_of(deadline(d(1))) is ReminderKind.ENDS_TOMORROW
        assert kind_of(deadline(d(DEADLINE_HEADS_UP_DAYS))) is ReminderKind.ENDS_SOON

    def test_no_end_warning_for_a_stage_that_has_not_started(self):
        """«Заканчивается через 3 дня» про неначавшийся этап — ошибка."""
        assert kind_of(range_(d(2), d(DEADLINE_HEADS_UP_DAYS))) is None

    def test_planned_today(self):
        assert kind_of(range_(d(-3), d(10)), planned_on=TODAY) is ReminderKind.PLANNED_TODAY

    def test_planned_tomorrow(self):
        assert kind_of(range_(d(-3), d(10)), planned_on=d(1)) is ReminderKind.PLANNED_TOMORROW

    def test_plan_wins_over_start_on_the_same_day(self):
        """Одна строка на этап: «по плану» важнее, чем «начинается»."""
        assert kind_of(single_day(TODAY), planned_on=TODAY) is ReminderKind.PLANNED_TODAY

    def test_todays_deadline_wins_over_tomorrows_plan(self):
        assert kind_of(range_(d(-3), TODAY), planned_on=d(1)) is ReminderKind.ENDS_TODAY

    def test_quiet_day_says_nothing(self):
        assert kind_of(range_(d(-3), d(10))) is None

    @pytest.mark.parametrize(
        "s",
        [
            stage(starts_on=d(1), start_precision=MONTH),
            stage(starts_on=d(-10), start_precision=DAY, ends_on=d(1), end_precision=MONTH),
            stage(),
        ],
        ids=["начало до месяца", "конец до месяца", "без дат"],
    )
    def test_nothing_without_an_exact_day(self, s):
        assert kind_of(s) is None

    def test_locked_stage_is_silent(self):
        assert kind_of(single_day(TODAY), locked=True) is None

    def test_answered_stage_is_silent(self):
        """Ответ на идущий этап — значит, его уже написали."""
        assert kind_of(range_(d(-3), TODAY), result=StageResult.PASSED) is None


class TestAskForResult:
    def test_day_after_the_end(self):
        assert kind_of(range_(d(-5), d(-1))) is ReminderKind.ASK_RESULT

    def test_day_after_a_single_day_stage(self):
        assert kind_of(single_day(d(-1))) is ReminderKind.ASK_RESULT

    def test_asked_once_not_every_day(self):
        assert kind_of(single_day(d(-2))) is None

    def test_registration_is_not_asked(self):
        assert kind_of(single_day(d(-1), kind=StageKind.REGISTRATION)) is None

    def test_already_answered_is_not_asked(self):
        assert kind_of(single_day(d(-1)), result=StageResult.FAILED) is None


class TestCollect:
    def test_sorted_by_section_then_day(self):
        o = olympiad()
        entries = [
            (o, range_(d(-5), d(-1), stage_id=1, name="А"), None, False),
            (o, single_day(d(1), stage_id=2, name="Б"), None, False),
            (o, single_day(TODAY, stage_id=3, name="В"), None, False),
            (o, deadline(d(DEADLINE_HEADS_UP_DAYS), stage_id=4, name="Г"), None, False),
        ]
        sections = [item.kind.section for item in collect_reminders(entries, {}, TODAY)]
        assert sections == [Section.TODAY, Section.TOMORROW, Section.SOON, Section.ASK]

    def test_plans_are_matched_by_stage(self):
        o = olympiad()
        entries = [(o, range_(d(-3), d(10), stage_id=7), None, False)]
        items = collect_reminders(entries, {7: TODAY}, TODAY)
        assert [i.kind for i in items] == [ReminderKind.PLANNED_TODAY]


class TestRender:
    def items(self, *stages, subject="Математика"):
        o = olympiad(subject=subject)
        return collect_reminders([(o, s, None, False) for s in stages], {}, TODAY)

    def test_nothing_to_say_means_no_message(self):
        assert render_digest([], TODAY) is None

    def test_header_names_the_day(self):
        text = render_digest(self.items(single_day(TODAY)), TODAY)
        assert text.startswith("Привет! Что важно на 14 октября:")

    def test_line_carries_stage_olympiad_and_subject(self):
        text = render_digest(self.items(single_day(TODAY, name="Заочный тур")), TODAY)
        assert "• Начинается «Заочный тур» — Высшая проба (Математика)" in text

    def test_subject_is_optional(self):
        text = render_digest(self.items(single_day(TODAY), subject=None), TODAY)
        assert "— Высшая проба\n" in text + "\n"

    def test_sections_have_titles(self):
        text = render_digest(
            self.items(
                single_day(TODAY, stage_id=1),
                single_day(d(1), stage_id=2),
                deadline(d(DEADLINE_HEADS_UP_DAYS), stage_id=3),
                single_day(d(-1), stage_id=4),
            ),
            TODAY,
        )
        for title in ("Сегодня", "Завтра", "Через 3 дня", "Как прошло?"):
            assert f"\n{title}\n" in text

    def test_ask_section_explains_why(self):
        text = render_digest(self.items(single_day(d(-1))), TODAY)
        assert "прошёл ли ты дальше" in text

    def test_long_digest_is_cut_with_a_pointer(self):
        many = [single_day(TODAY, stage_id=i, name=f"Этап {i}") for i in range(MAX_ITEMS + 5)]
        text = render_digest(self.items(*many), TODAY)
        assert text.count("\n• ") == MAX_ITEMS
        assert "И ещё 5 — в приложении." in text

    def test_never_longer_than_max_allows(self):
        """Даже с очень длинными названиями сообщение пройдёт по лимиту."""
        long_name = "Олимпиада " * 60
        o = olympiad(name=long_name)
        entries = [
            (o, single_day(TODAY, stage_id=i, name="Этап " * 20), None, False)
            for i in range(MAX_ITEMS)
        ]
        text = render_digest(collect_reminders(entries, {}, TODAY), TODAY)
        assert len(text) <= MAX_TEXT_LENGTH
        assert "в приложении." in text


class TestIsDue:
    def test_before_time(self):
        assert not is_due(time(8, 59), time(9, 0))

    def test_at_time(self):
        assert is_due(time(9, 0), time(9, 0))

    def test_late_start_after_an_outage_is_still_fine(self):
        assert is_due(time(14, 30), time(9, 0))

    def test_not_at_night(self):
        assert not is_due(LATEST_START, time(9, 0))

    def test_deliberately_late_time_still_fires(self):
        assert is_due(time(22, 30), time(22, 0))


class FakeRun:
    def __init__(self, aborted=False):
        self.calls = []
        self.aborted = aborted

    async def __call__(self, session_factory, client, settings, today, **kwargs):
        self.calls.append(today)
        return PassStats(day=today, aborted=self.aborted)


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class Settings:
    reminder_time = time(9, 0)


def scheduler(clock, run):
    return ReminderScheduler(None, None, Settings(), now=clock, run=run)


class TestScheduler:
    async def test_waits_for_the_time(self):
        run = FakeRun()
        await scheduler(Clock(datetime(2026, 10, 14, 8, 30)), run).tick()
        assert run.calls == []

    async def test_runs_once_a_day(self):
        run, clock = FakeRun(), Clock(datetime(2026, 10, 14, 9, 0))
        s = scheduler(clock, run)
        await s.tick()
        clock.value = datetime(2026, 10, 14, 9, 1)
        await s.tick()
        clock.value = datetime(2026, 10, 14, 15, 0)
        await s.tick()
        assert run.calls == [date(2026, 10, 14)]

    async def test_runs_again_next_day(self):
        run, clock = FakeRun(), Clock(datetime(2026, 10, 14, 9, 0))
        s = scheduler(clock, run)
        await s.tick()
        clock.value = datetime(2026, 10, 15, 9, 0)
        await s.tick()
        assert run.calls == [date(2026, 10, 14), date(2026, 10, 15)]

    async def test_after_abort_waits_before_retrying(self):
        run, clock = FakeRun(aborted=True), Clock(datetime(2026, 10, 14, 9, 0))
        s = scheduler(clock, run)
        await s.tick()
        clock.value = datetime(2026, 10, 14, 9, 5)
        await s.tick()
        assert len(run.calls) == 1
        clock.value = datetime(2026, 10, 14, 9, 0) + RETRY_AFTER_ABORT
        await s.tick()
        assert len(run.calls) == 2

    async def test_restart_mid_day_runs_again_and_lets_the_journal_decide(self):
        """Новый процесс не помнит утренний проход — и не должен.

        Кому уже отправлено, решает журнал в базе; планировщику достаточно
        запустить проход ещё раз.
        """
        run = FakeRun()
        await scheduler(Clock(datetime(2026, 10, 14, 11, 0)), run).tick()
        assert run.calls == [date(2026, 10, 14)]
