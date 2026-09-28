"""Тесты каталога: определение типа этапа, ключи и статусы.

Названия этапов взяты из реальной выгрузки — на выдуманных примерах
эвристика выглядит надёжнее, чем есть.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.catalog.dates import Precision
from app.catalog.importer import build_external_key, classify_stage
from app.catalog.models import Stage, StageKind
from app.api.catalog import StageOut
from app.catalog.presentation import (
    StageStatus,
    days_until_start,
    has_known_dates,
    is_plannable,
    stage_status,
)

TODAY = date(2026, 10, 1)


def make_stage(
    starts_on=None,
    start_precision=None,
    ends_on=None,
    end_precision=None,
) -> Stage:
    return Stage(
        id=1,
        external_key="k",
        name="Этап",
        kind=StageKind.OTHER,
        starts_on=starts_on,
        start_precision=start_precision,
        ends_on=ends_on,
        end_precision=end_precision,
    )


class TestClassifyStage:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Регистрация", StageKind.REGISTRATION),
            ("Регистрация на олимпиаду", StageKind.REGISTRATION),
            ("Отборочный этап", StageKind.QUALIFYING),
            ("Первый отборочный тур", StageKind.QUALIFYING),
            ("Квалификационный этап", StageKind.QUALIFYING),
            ("Пригласительный этап", StageKind.QUALIFYING),
            ("Ознакомительный раунд", StageKind.QUALIFYING),
            ("Подготовительный тур", StageKind.QUALIFYING),
            ("Финальный этап", StageKind.FINAL),
            ("Заключительный этап", StageKind.FINAL),
            ("Второй (заключительный) тур", StageKind.FINAL),
            ("Очный тур", StageKind.OTHER),
            ("Подведение итогов", StageKind.OTHER),
            ("Тематический урок по финансовой безопасности", StageKind.OTHER),
        ],
    )
    def test_known_names(self, name, expected):
        assert classify_stage(name) is expected

    def test_registration_wins_over_stage_name(self):
        """«Регистрация на заключительный этап» — это регистрация.

        Порядок правил важен: проверка на финал сработала бы первой и
        отправила бы пользователя не на тот этап.
        """
        assert classify_stage("Регистрация на заключительный этап") is StageKind.REGISTRATION
        assert classify_stage("Регистрация на отборочный этап") is StageKind.REGISTRATION

    def test_empty_name(self):
        assert classify_stage("") is StageKind.OTHER


class TestExternalKey:
    def test_slug_from_url(self):
        key = build_external_key(
            {"url": "https://postupi.online/olimpiada/x/etap/pervyj-otborochnyj-etap/"}
        )

        assert key == "pervyj-otborochnyj-etap"

    def test_falls_back_to_name(self):
        assert build_external_key({"url": "", "name": "  Отборочный  этап "}) == "отборочный этап"

    def test_key_is_stable_when_title_changes(self):
        """Ключ из ссылки не должен зависеть от правок названия.

        Иначе при каждом обновлении источника этап пересоздаётся, и
        прогресс пользователя теряет привязку.
        """
        base = "https://postupi.online/olimpiada/x/etap/final/"

        assert build_external_key({"url": base, "name": "Финал"}) == build_external_key(
            {"url": base, "name": "Финальный этап 2027"}
        )

    def test_empty_payload(self):
        assert build_external_key({}) == "stage"


class TestStageStatus:
    def test_upcoming(self):
        stage = make_stage(date(2026, 11, 5), Precision.DAY, date(2026, 12, 11), Precision.DAY)

        assert stage_status(stage, TODAY) is StageStatus.UPCOMING

    def test_active(self):
        stage = make_stage(date(2026, 9, 17), Precision.DAY, date(2026, 10, 23), Precision.DAY)

        assert stage_status(stage, TODAY) is StageStatus.ACTIVE

    def test_finished(self):
        stage = make_stage(date(2026, 2, 1), Precision.DAY, date(2026, 3, 10), Precision.DAY)

        assert stage_status(stage, TODAY) is StageStatus.FINISHED

    def test_unknown_without_dates(self):
        assert stage_status(make_stage(), TODAY) is StageStatus.UNKNOWN

    def test_month_precision_compares_by_month(self):
        """Этап «март 2027» не начался, пока не наступил март 2027."""
        stage = make_stage(date(2027, 3, 1), Precision.MONTH)

        assert stage_status(stage, TODAY) is StageStatus.UPCOMING

    def test_current_month_is_active(self):
        stage = make_stage(date(2026, 10, 1), Precision.MONTH, date(2026, 11, 1), Precision.MONTH)

        assert stage_status(stage, TODAY) is StageStatus.ACTIVE


class TestDaysUntilStart:
    def test_exact_date(self):
        stage = make_stage(date(2026, 10, 6), Precision.DAY)

        assert days_until_start(stage, TODAY) == 5

    def test_month_precision_gives_none(self):
        """Для «март 2027» таймер посчитать нельзя — только null.

        Если вернуть число, интерфейс покажет обратный отсчёт до первого
        марта, которого в источнике нет.
        """
        stage = make_stage(date(2027, 3, 1), Precision.MONTH)

        assert days_until_start(stage, TODAY) is None

    def test_no_date_gives_none(self):
        assert days_until_start(make_stage(), TODAY) is None


class TestPlannable:
    def test_exact_date_is_plannable(self):
        assert is_plannable(make_stage(date(2026, 10, 6), Precision.DAY))

    def test_month_precision_is_not_plannable(self):
        assert not is_plannable(make_stage(date(2027, 3, 1), Precision.MONTH))

    def test_missing_date_is_not_plannable(self):
        assert not is_plannable(make_stage())


class TestStageDates:
    """Даты этапа в карточке — те же, что календарь отдаёт в start_stage и end_stage."""

    @staticmethod
    def dates(stage: Stage):
        out = StageOut.build(stage, TODAY)
        return (
            out.date_precision.value,
            out.starts_on,
            out.start_precision,
            out.ends_on,
            out.end_precision,
        )

    def test_exact_has_end_equal_to_start(self):
        """В базе у однодневного этапа конца нет, а у парсера он равен началу."""
        stage = make_stage(date(2026, 10, 4), Precision.DAY)

        assert self.dates(stage) == (
            "exact", date(2026, 10, 4), "day", date(2026, 10, 4), "day",
        )

    def test_range(self):
        stage = make_stage(date(2026, 10, 5), Precision.DAY, date(2026, 10, 20), Precision.DAY)

        assert self.dates(stage) == (
            "range", date(2026, 10, 5), "day", date(2026, 10, 20), "day",
        )

    def test_until_has_no_start(self):
        stage = make_stage(ends_on=date(2026, 10, 10), end_precision=Precision.DAY)

        assert self.dates(stage) == ("until", None, None, date(2026, 10, 10), "day")

    def test_reversed_range_is_a_single_day(self):
        """Календарь рисует такой этап кружком — карточка не спорит с ним."""
        stage = make_stage(date(2026, 11, 5), Precision.DAY, date(2026, 11, 1), Precision.DAY)

        assert self.dates(stage) == (
            "exact", date(2026, 11, 5), "day", date(2026, 11, 5), "day",
        )

    def test_month_precision_stays_as_is(self):
        stage = make_stage(date(2027, 3, 1), Precision.MONTH)

        assert self.dates(stage) == ("unknown", date(2027, 3, 1), "month", None, None)

    def test_no_dates(self):
        assert self.dates(make_stage()) == ("unknown", None, None, None, None)


class TestHasKnownDates:
    """Фильтр «с известными датами» во вкладках «Поиск» и «Мои»."""

    def test_no_stages(self):
        assert has_known_dates([]) is False

    def test_only_tbd(self):
        assert has_known_dates([make_stage()]) is False

    def test_month_counts(self):
        assert has_known_dates([make_stage(), make_stage(date(2027, 3, 1), Precision.MONTH)])

    def test_finished_stage_counts(self):
        """Расписание есть, хоть всё и прошло — в отличие от next_stage."""
        assert has_known_dates([make_stage(date(2025, 3, 1), Precision.DAY)])
