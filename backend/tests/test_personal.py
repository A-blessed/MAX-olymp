"""Тесты правил механики и ленты новостей.

Правила — чистые функции, поэтому проверяются без базы: каждое
предложение из описания механики превращается здесь в отдельный тест.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.catalog.dates import Precision
from app.catalog.models import Olympiad, Stage, StageKind, Subject
from app.personal.models import StageResult
from app.personal.news import (
    NewsCategory,
    build_feed,
    classify,
    dates_added,
    human_date_range,
    plural_days,
)
from app.personal.rules import (
    DAILY_PLAN_LIMIT,
    RuleViolation,
    awaits_answer,
    check_can_answer,
    check_can_plan,
    is_eliminated,
    locked_stage_ids,
    plan_window,
)

TODAY = date(2026, 10, 1)
DAY = Precision.DAY
MONTH = Precision.MONTH


def stage(
    stage_id: int = 1,
    position: int = 0,
    starts_on=None,
    start_precision=None,
    ends_on=None,
    end_precision=None,
    kind: StageKind = StageKind.QUALIFYING,
    name: str = "Отборочный этап",
) -> Stage:
    return Stage(
        id=stage_id,
        position=position,
        external_key=f"k{stage_id}",
        name=name,
        kind=kind,
        starts_on=starts_on,
        start_precision=start_precision,
        ends_on=ends_on,
        end_precision=end_precision,
        raw_date_range="",
    )


def olympiad() -> Olympiad:
    return Olympiad(id=10, name="Олимпиада", source_url="https://example/o/")


def violation_code(func, *args, **kwargs):
    with pytest.raises(RuleViolation) as caught:
        func(*args, **kwargs)
    return caught.value.code


# ---------------------------------------------------------------------
# Окно планирования
# ---------------------------------------------------------------------


class TestPlanWindow:
    def test_exact_range(self):
        s = stage(starts_on=date(2026, 9, 17), start_precision=DAY,
                  ends_on=date(2026, 10, 23), end_precision=DAY)

        assert plan_window(s) == (date(2026, 9, 17), date(2026, 10, 23))

    def test_end_known_to_month_extends_to_month_end(self):
        s = stage(starts_on=date(2026, 11, 5), start_precision=DAY,
                  ends_on=date(2026, 12, 1), end_precision=MONTH)

        assert plan_window(s) == (date(2026, 11, 5), date(2026, 12, 31))

    def test_no_end_means_single_day(self):
        s = stage(starts_on=date(2026, 11, 5), start_precision=DAY)

        assert plan_window(s) == (date(2026, 11, 5), date(2026, 11, 5))

    def test_month_start_is_not_plannable(self):
        """«Март 2027» на конкретный день календаря не положишь."""
        s = stage(starts_on=date(2027, 3, 1), start_precision=MONTH)

        assert plan_window(s) is None

    def test_reversed_dates_do_not_invert_window(self):
        s = stage(starts_on=date(2026, 11, 5), start_precision=DAY,
                  ends_on=date(2026, 11, 1), end_precision=DAY)

        assert plan_window(s) == (date(2026, 11, 5), date(2026, 11, 5))


# ---------------------------------------------------------------------
# Блокировка после «не прошёл»
# ---------------------------------------------------------------------


class TestLocking:
    def setup_method(self):
        self.stages = [stage(stage_id=i, position=i) for i in range(1, 5)]

    def test_nothing_locked_without_failure(self):
        assert locked_stage_ids(self.stages, {1: StageResult.PASSED}) == set()

    def test_failure_locks_everything_after(self):
        """«Не прошёл» означает конец олимпиады."""
        assert locked_stage_ids(self.stages, {2: StageResult.FAILED}) == {3, 4}

    def test_failed_stage_itself_stays_open(self):
        """Иначе ошибочный ответ нельзя было бы исправить."""
        assert 2 not in locked_stage_ids(self.stages, {2: StageResult.FAILED})

    def test_failure_on_last_stage_locks_nothing(self):
        assert locked_stage_ids(self.stages, {4: StageResult.FAILED}) == set()

    def test_order_is_by_position_not_by_list_order(self):
        shuffled = list(reversed(self.stages))

        assert locked_stage_ids(shuffled, {2: StageResult.FAILED}) == {3, 4}

    def test_eliminated(self):
        assert is_eliminated([StageResult.PASSED, StageResult.FAILED])
        assert not is_eliminated([StageResult.PASSED])
        assert not is_eliminated([])


# ---------------------------------------------------------------------
# «Ожидает ответа от тебя»
# ---------------------------------------------------------------------


class TestAwaitsAnswer:
    finished = dict(starts_on=date(2026, 9, 1), start_precision=DAY,
                    ends_on=date(2026, 9, 20), end_precision=DAY)

    def test_finished_stage_without_answer(self):
        assert awaits_answer(stage(**self.finished), None, False, TODAY)

    def test_answered_stage_does_not_wait(self):
        assert not awaits_answer(stage(**self.finished), StageResult.PASSED, False, TODAY)

    def test_registration_is_never_asked(self):
        """«Прошёл ли ты регистрацию?» — вопрос без смысла."""
        s = stage(kind=StageKind.REGISTRATION, **self.finished)

        assert not awaits_answer(s, None, False, TODAY)

    def test_locked_stage_does_not_wait(self):
        assert not awaits_answer(stage(**self.finished), None, True, TODAY)

    def test_active_stage_does_not_wait(self):
        s = stage(starts_on=date(2026, 9, 17), start_precision=DAY,
                  ends_on=date(2026, 10, 23), end_precision=DAY)

        assert not awaits_answer(s, None, False, TODAY)


# ---------------------------------------------------------------------
# Можно ли ответить
# ---------------------------------------------------------------------


class TestCheckCanAnswer:
    active = dict(starts_on=date(2026, 9, 17), start_precision=DAY,
                  ends_on=date(2026, 10, 23), end_precision=DAY)

    def test_active_stage_can_be_answered(self):
        """Отборочный пишут в начале окна, результаты приходят до закрытия."""
        check_can_answer(stage(**self.active), saved=True, locked=False, today=TODAY)

    def test_not_saved(self):
        code = violation_code(check_can_answer, stage(**self.active),
                              saved=False, locked=False, today=TODAY)
        assert code == "not_saved"

    def test_locked(self):
        code = violation_code(check_can_answer, stage(**self.active),
                              saved=True, locked=True, today=TODAY)
        assert code == "stage_locked"

    def test_upcoming_stage_cannot_be_answered(self):
        s = stage(starts_on=date(2026, 11, 5), start_precision=DAY)

        code = violation_code(check_can_answer, s, saved=True, locked=False, today=TODAY)
        assert code == "stage_not_started"


# ---------------------------------------------------------------------
# Можно ли запланировать
# ---------------------------------------------------------------------


class TestCheckCanPlan:
    window = dict(starts_on=date(2026, 9, 17), start_precision=DAY,
                  ends_on=date(2026, 10, 23), end_precision=DAY)

    def plan(self, day, stage_obj=None, **overrides):
        params = dict(saved=True, locked=False, today=TODAY,
                      existing_plan=None, planned_that_day=0)
        params.update(overrides)
        return check_can_plan(stage_obj or stage(**self.window), day, **params)

    def code(self, day, **overrides):
        with pytest.raises(RuleViolation) as caught:
            self.plan(day, **overrides)
        return caught.value.code

    def test_day_inside_window(self):
        self.plan(date(2026, 10, 5))

    def test_first_and_last_day_of_window_are_allowed(self):
        self.plan(TODAY)
        self.plan(date(2026, 10, 23))

    def test_not_saved(self):
        assert self.code(date(2026, 10, 5), saved=False) == "not_saved"

    def test_locked(self):
        assert self.code(date(2026, 10, 5), locked=True) == "stage_locked"

    def test_month_precision_is_rejected(self):
        rough = stage(starts_on=date(2027, 3, 1), start_precision=MONTH)

        assert self.code(date(2027, 3, 10), stage_obj=rough) == "not_plannable"

    def test_outside_window(self):
        assert self.code(date(2026, 10, 24)) == "date_outside_stage"

    def test_past_day(self):
        """День внутри окна, но уже прошедший."""
        assert self.code(date(2026, 9, 20)) == "date_in_past"

    def test_same_day_again_is_noop(self):
        self.plan(date(2026, 10, 5), existing_plan=date(2026, 10, 5))

    def test_other_day_is_locked(self):
        """По механике: выбран на другой день — серый, с замком."""
        assert self.code(date(2026, 10, 6), existing_plan=date(2026, 10, 5)) == (
            "already_planned_other_day"
        )

    def test_below_limit_is_allowed(self):
        self.plan(date(2026, 10, 5), planned_that_day=DAILY_PLAN_LIMIT - 1)

    def test_limit_reached(self):
        """До трёх олимпиад в день; четвёртая — отказ."""
        assert self.code(date(2026, 10, 5), planned_that_day=DAILY_PLAN_LIMIT) == (
            "day_limit_reached"
        )

    def test_limit_does_not_block_already_selected(self):
        """Повторная отметка уже выбранного не считается четвёртой."""
        self.plan(date(2026, 10, 5), existing_plan=date(2026, 10, 5),
                  planned_that_day=DAILY_PLAN_LIMIT)


# ---------------------------------------------------------------------
# Новости
# ---------------------------------------------------------------------


class TestPluralDays:
    @pytest.mark.parametrize(
        "count,expected",
        [
            (1, "1 день"), (2, "2 дня"), (4, "4 дня"), (5, "5 дней"),
            (11, "11 дней"), (12, "12 дней"), (14, "14 дней"),
            (21, "21 день"), (22, "22 дня"), (25, "25 дней"),
            (101, "101 день"), (111, "111 дней"),
        ],
    )
    def test_russian_plural(self, count, expected):
        assert plural_days(count) == expected


class TestNewsClassify:
    def news(self, s, result=None, locked=False):
        return classify(s, olympiad(), result=result, locked=locked, today=TODAY)

    def test_starts_today_is_urgent(self):
        item = self.news(stage(starts_on=TODAY, start_precision=DAY,
                               ends_on=TODAY + timedelta(days=5), end_precision=DAY))

        assert item.category is NewsCategory.URGENT
        assert "сегодня" in item.message

    def test_ends_today_is_urgent(self):
        item = self.news(stage(starts_on=TODAY - timedelta(days=5), start_precision=DAY,
                               ends_on=TODAY, end_precision=DAY))

        assert item.category is NewsCategory.URGENT
        assert "заканчивается сегодня" in item.message

    def test_starts_within_week_is_soon(self):
        item = self.news(stage(starts_on=TODAY + timedelta(days=3), start_precision=DAY))

        assert item.category is NewsCategory.SOON
        assert "через 3 дня" in item.message

    def test_ends_within_week_is_soon(self):
        item = self.news(stage(starts_on=TODAY - timedelta(days=10), start_precision=DAY,
                               ends_on=TODAY + timedelta(days=5), end_precision=DAY))

        assert item.category is NewsCategory.SOON
        assert "заканчивается через 5 дней" in item.message

    def test_week_boundary_is_soon(self):
        item = self.news(stage(starts_on=TODAY + timedelta(days=7), start_precision=DAY))

        assert item.category is NewsCategory.SOON

    def test_beyond_week_is_later(self):
        item = self.news(stage(starts_on=TODAY + timedelta(days=8), start_precision=DAY))

        assert item.category is NewsCategory.LATER

    def test_month_precision_is_never_urgent_or_soon(self):
        """Этап «октябрь 2026» идёт прямо сейчас, но «через N дней» — выдумка."""
        s = stage(starts_on=date(2026, 10, 1), start_precision=MONTH,
                  ends_on=date(2026, 10, 1), end_precision=MONTH)
        s.raw_date_range = "окт 2026"

        item = self.news(s)
        assert item.category is NewsCategory.LATER
        assert "окт 2026" in item.message

    def test_finished_without_answer_awaits(self):
        item = self.news(stage(starts_on=date(2026, 9, 1), start_precision=DAY,
                               ends_on=date(2026, 9, 20), end_precision=DAY))

        assert item.category is NewsCategory.AWAITING_ANSWER

    def test_finished_with_answer_is_finished(self):
        item = self.news(stage(starts_on=date(2026, 9, 1), start_precision=DAY,
                               ends_on=date(2026, 9, 20), end_precision=DAY),
                         result=StageResult.PASSED)

        assert item.category is NewsCategory.FINISHED
        assert item.result is StageResult.PASSED

    def test_locked_stage_is_hidden(self):
        """После «не прошёл» следующие этапы не должны всплывать в ленте."""
        assert self.news(stage(starts_on=TODAY, start_precision=DAY), locked=True) is None

    def test_stage_without_dates_is_hidden(self):
        assert self.news(stage()) is None


def test_feed_orders_by_event_date():
    later = stage(stage_id=1, starts_on=TODAY + timedelta(days=30), start_precision=DAY)
    sooner = stage(stage_id=2, starts_on=TODAY + timedelta(days=10), start_precision=DAY)

    feed = build_feed(
        [(olympiad(), later, None, False), (olympiad(), sooner, None, False)],
        today=TODAY,
    )

    assert [item.stage_id for item in feed.later] == [2, 1]


class TestHumanDateRange:
    @pytest.mark.parametrize(
        "dates,expected",
        [
            (dict(starts_on=date(2026, 9, 25), start_precision=DAY,
                  ends_on=date(2026, 10, 15), end_precision=DAY),
             "25 сентября – 15 октября 2026"),
            (dict(starts_on=date(2026, 12, 4), start_precision=DAY,
                  ends_on=date(2026, 12, 17), end_precision=DAY),
             "4–17 декабря 2026"),
            (dict(starts_on=date(2026, 12, 15), start_precision=DAY,
                  ends_on=date(2027, 1, 20), end_precision=DAY),
             "15 декабря 2026 – 20 января 2027"),
            (dict(starts_on=date(2026, 10, 4), start_precision=DAY), "4 октября 2026"),
            (dict(ends_on=date(2026, 11, 18), end_precision=DAY), "до 18 ноября 2026"),
            (dict(starts_on=date(2027, 3, 1), start_precision=MONTH), None),
            (dict(), None),
        ],
    )
    def test_formats(self, dates, expected):
        assert human_date_range(stage(**dates)) == expected


class TestAwaitingAnswerItem:
    """Карточка «Ожидает ответа от тебя»: кнопки рисуются по stage_id."""

    def test_fields_for_the_card(self):
        oly = olympiad()
        oly.subject = Subject(id=3, name="Химия")
        s = stage(7, starts_on=date(2026, 9, 1), start_precision=DAY,
                  ends_on=date(2026, 9, 16), end_precision=DAY)

        item = classify(s, oly, result=None, locked=False, today=TODAY)

        assert item.category is NewsCategory.AWAITING_ANSWER
        assert (item.stage_id, item.subject_name) == (7, "Химия")
        assert item.plan_window_end == date(2026, 9, 16)
        assert item.message == "Подтверди, прошёл ли ты в следующий этап"
        assert item.badge == "Ожидает ответа"

    def test_deadline_window_ends_on_the_deadline(self):
        s = stage(ends_on=date(2026, 9, 20), end_precision=DAY)

        item = classify(s, olympiad(), result=None, locked=False, today=TODAY)

        assert item.category is NewsCategory.AWAITING_ANSWER
        assert item.plan_window_end == date(2026, 9, 20)

    def test_window_not_over_yet_is_not_awaiting(self):
        s = stage(starts_on=date(2026, 9, 1), start_precision=DAY,
                  ends_on=TODAY, end_precision=DAY)

        item = classify(s, olympiad(), result=None, locked=False, today=TODAY)

        assert item.category is not NewsCategory.AWAITING_ANSWER

    def test_answer_moves_stage_out(self):
        s = stage(starts_on=date(2026, 9, 1), start_precision=DAY,
                  ends_on=date(2026, 9, 16), end_precision=DAY)

        feed = build_feed([(olympiad(), s, StageResult.FAILED, False)], today=TODAY)

        assert feed.awaiting_answer == []
        assert [item.stage_id for item in feed.finished] == [s.id]

    def test_longest_waiting_first(self):
        recent = stage(1, starts_on=date(2026, 9, 1), start_precision=DAY,
                       ends_on=date(2026, 9, 25), end_precision=DAY)
        old = stage(2, starts_on=date(2026, 9, 1), start_precision=DAY,
                    ends_on=date(2026, 9, 10), end_precision=DAY)

        feed = build_feed(
            [(olympiad(), recent, None, False), (olympiad(), old, None, False)], today=TODAY
        )

        assert [item.stage_id for item in feed.awaiting_answer] == [2, 1]


class TestDatesAdded:
    SAVED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    IMPORTED_AT = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)

    def upcoming(self, stage_id=1, dates_added_at=IMPORTED_AT, **overrides):
        dates = dict(starts_on=date(2026, 10, 25), start_precision=DAY,
                     ends_on=date(2026, 11, 15), end_precision=DAY)
        dates.update(overrides)
        s = stage(stage_id, **dates)
        s.dates_added_at = dates_added_at
        return s

    def news(self, s, locked=False, saved_at=SAVED_AT):
        return dates_added(s, olympiad(), locked=locked, today=TODAY, saved_at=saved_at)

    def test_item_for_the_card(self):
        item = self.news(self.upcoming())

        assert item.category is NewsCategory.DATES_ADDED
        assert item.date_range == "25 октября – 15 ноября 2026"
        assert (item.message, item.badge) == ("Появились даты этапа", "Появились даты")
        assert item.created_at == self.IMPORTED_AT

    def test_dates_known_since_before_saving_are_not_news(self):
        assert self.news(self.upcoming(), saved_at=self.IMPORTED_AT + timedelta(hours=1)) is None

    def test_stage_that_never_lacked_dates_is_not_news(self):
        assert self.news(self.upcoming(dates_added_at=None)) is None

    def test_finished_stage_drops_out(self):
        s = self.upcoming(starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 20))
        assert self.news(s) is None

    def test_locked_stage_drops_out(self):
        assert self.news(self.upcoming(), locked=True) is None

    def test_dates_gone_again_drop_out(self):
        s = self.upcoming(starts_on=None, start_precision=None, ends_on=None, end_precision=None)
        assert self.news(s) is None

    def test_stage_stays_in_its_own_category_too(self):
        s = self.upcoming(starts_on=TODAY + timedelta(days=3), ends_on=None, end_precision=None)

        feed = build_feed([(olympiad(), s, None, False)], today=TODAY,
                          saved_at={10: self.SAVED_AT})

        assert [item.stage_id for item in feed.soon] == [s.id]
        assert [item.stage_id for item in feed.dates_added] == [s.id]

    def test_newest_first_then_nearest_stage(self):
        earlier_import = self.upcoming(1, dates_added_at=self.IMPORTED_AT - timedelta(days=3))
        far = self.upcoming(2, starts_on=date(2026, 12, 1), ends_on=date(2026, 12, 5))
        near = self.upcoming(3, starts_on=date(2026, 10, 10), ends_on=date(2026, 10, 12))

        feed = build_feed(
            [(olympiad(), s, None, False) for s in (earlier_import, far, near)],
            today=TODAY,
            saved_at={10: self.SAVED_AT},
        )

        assert [item.stage_id for item in feed.dates_added] == [3, 2, 1]


# ---------------------------------------------------------------------
# Календарь по олимпиадам
# ---------------------------------------------------------------------


class TestCalendarOlympiads:
    """Поля, по которым рисует календарь фронтенда: start_stage, end_stage."""

    @staticmethod
    def build(*stages, subject=True, plans=None):
        from app.api.personal import calendar_olympiads
        from app.catalog.models import Subject

        oly = olympiad()
        if subject:
            oly.subject = Subject(id=3, name="Физика", color="#F5E6C8")
            oly.subject_id = 3
        visible = [(oly, s, plan_window(s)) for s in stages]
        return calendar_olympiads(visible, plans or {})

    def test_range_exact_and_until(self):
        (item,) = self.build(
            stage(1, starts_on=date(2026, 10, 5), start_precision=DAY,
                  ends_on=date(2026, 10, 20), end_precision=DAY),
            stage(2, starts_on=date(2026, 10, 4), start_precision=DAY),
            stage(3, ends_on=date(2026, 10, 10), end_precision=DAY,
                  kind=StageKind.REGISTRATION, name="Регистрация"),
        )

        assert (item.name, item.subject, item.color) == ("Олимпиада", "Физика", "#F5E6C8")
        got = [(s.date_precision.value, s.start_stage, s.end_stage) for s in item.stages]
        assert got == [
            ("range", date(2026, 10, 5), date(2026, 10, 20)),
            ("exact", date(2026, 10, 4), date(2026, 10, 4)),
            # Окно у дедлайна строится назад от срока, но это не начало этапа.
            ("until", None, date(2026, 10, 10)),
        ]

    def test_exact_start_with_month_end_stays_a_single_day(self):
        (item,) = self.build(
            stage(1, starts_on=date(2026, 10, 5), start_precision=DAY,
                  ends_on=date(2026, 11, 1), end_precision=MONTH),
        )
        assert (item.stages[0].start_stage, item.stages[0].end_stage) == (
            date(2026, 10, 5), date(2026, 10, 5),
        )

    def test_plans_and_missing_subject(self):
        (item,) = self.build(
            stage(7, starts_on=date(2026, 10, 5), start_precision=DAY),
            subject=False,
            plans={7: date(2026, 10, 5)},
        )
        assert item.subject is None and item.color is None
        assert item.stages[0].planned_on == date(2026, 10, 5)

    def test_source_text_for_the_day_window(self):
        s = stage(1, starts_on=date(2026, 10, 5), start_precision=DAY)
        s.raw_date_range = "5 окт"

        (item,) = self.build(s)

        assert item.stages[0].source_text == "5 окт"

    def test_deadline_window_matches_calendar_bar(self):
        """Фронтенд рисует полосу «до срока» на 10 дней — столько же даёт и окно."""
        s = stage(1, ends_on=date(2026, 10, 30), end_precision=DAY)

        assert plan_window(s) == (date(2026, 10, 20), date(2026, 10, 30))


class TestDetailMatchesCalendar:
    """Карточка в «Моих олимпиадах» и календарь отдают этап одинаково."""

    STAGES = [
        stage(1, starts_on=date(2026, 10, 5), start_precision=DAY,
              ends_on=date(2026, 10, 20), end_precision=DAY),
        stage(2, starts_on=date(2026, 10, 4), start_precision=DAY),
        stage(3, ends_on=date(2026, 10, 10), end_precision=DAY,
              kind=StageKind.REGISTRATION, name="Регистрация"),
        stage(4, starts_on=date(2026, 10, 5), start_precision=DAY,
              ends_on=date(2026, 11, 1), end_precision=MONTH),
    ]

    def test_same_dates_and_windows(self):
        from app.api.personal import MyStageOut, calendar_olympiads

        oly = olympiad()
        visible = [(oly, s, plan_window(s)) for s in self.STAGES]
        (calendar_item,) = calendar_olympiads(visible, {})
        in_calendar = {
            s.stage_id: (s.date_precision, s.start_stage, s.end_stage, *window)
            for s, (_, _, window) in zip(calendar_item.stages, visible)
        }

        for s in self.STAGES:
            card = MyStageOut.build_personal(
                s, TODAY, result=None, planned_on=None, locked=False
            )
            assert (
                card.date_precision,
                card.starts_on,
                card.ends_on,
                card.plan_window_start,
                card.plan_window_end,
            ) == in_calendar[s.id]
