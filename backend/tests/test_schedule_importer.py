"""Тесты разбора выгрузки парсера olimpiada.ru.

Случаи взяты из настоящего файла: у ``exact`` парсер кладёт один и тот же
день в оба поля, у ``until`` начала нет вовсе, а ``range`` иногда
схлопывается в один день.

Отдельно проверяется круг: значение парсера → поля модели → значение,
вычисленное для календаря. Он должен замыкаться, иначе интерфейс нарисует
не ту фигуру.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.catalog.dates import Precision
from app.catalog.models import Stage
from app.catalog.presentation import DatePrecision, date_precision
from app.catalog.schedule_importer import (
    build_activity_index,
    parse_iso,
    stage_dates,
    stage_external_key,
)


def make_stage(payload):
    """Этап так, как его записал бы импорт."""
    starts_on, start_precision, ends_on, end_precision = stage_dates(payload)
    stage = Stage(external_key="k", name="Этап")
    stage.starts_on = starts_on
    stage.start_precision = start_precision
    stage.ends_on = ends_on
    stage.end_precision = end_precision
    return stage


class TestParseIso:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026-12-04", date(2026, 12, 4)),
            ("  2026-12-04  ", date(2026, 12, 4)),
        ],
    )
    def test_reads_iso(self, raw, expected):
        assert parse_iso(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "4 дек", "2026-13-01", 20261204])
    def test_everything_else_is_none(self, raw):
        assert parse_iso(raw) is None


class TestStageDates:
    def test_range_keeps_both_ends(self):
        assert stage_dates(
            {"date_precision": "range", "start_stage": "2026-12-04", "end_stage": "2026-12-17"}
        ) == (date(2026, 12, 4), Precision.DAY, date(2026, 12, 17), Precision.DAY)

    def test_exact_keeps_only_start(self):
        """Парсер дублирует день в оба поля, но это точка, а не диапазон."""
        assert stage_dates(
            {"date_precision": "exact", "start_stage": "2026-10-04", "end_stage": "2026-10-04"}
        ) == (date(2026, 10, 4), Precision.DAY, None, None)

    def test_range_of_one_day_collapses_to_a_point(self):
        assert stage_dates(
            {"date_precision": "range", "start_stage": "2026-10-04", "end_stage": "2026-10-04"}
        ) == (date(2026, 10, 4), Precision.DAY, None, None)

    def test_until_has_no_start(self):
        """Дедлайн — не начало. Подставить его значило бы соврать таймеру."""
        assert stage_dates(
            {"date_precision": "until", "start_stage": None, "end_stage": "2026-11-18"}
        ) == (None, None, date(2026, 11, 18), Precision.DAY)

    def test_unknown_gives_nothing(self):
        assert stage_dates(
            {"date_precision": "unknown", "start_stage": None, "end_stage": None}
        ) == (None, None, None, None)

    def test_until_without_deadline_gives_nothing(self):
        assert stage_dates(
            {"date_precision": "until", "start_stage": None, "end_stage": None}
        ) == (None, None, None, None)

    def test_reversed_range_is_not_a_range(self):
        """Перепутанные даты не должны давать вывернутое окно."""
        starts_on, _, ends_on, _ = stage_dates(
            {"date_precision": "range", "start_stage": "2026-12-17", "end_stage": "2026-12-04"}
        )
        assert starts_on == date(2026, 12, 17)
        assert ends_on is None

    def test_unknown_precision_name_is_not_trusted(self):
        assert stage_dates(
            {"date_precision": "чтото", "start_stage": "2026-12-04", "end_stage": None}
        ) == (None, None, None, None)


class TestRoundTrip:
    """Значение парсера должно возвращаться тем же после записи в модель."""

    @pytest.mark.parametrize(
        "payload,expected",
        [
            (
                {"date_precision": "range", "start_stage": "2026-12-04", "end_stage": "2026-12-17"},
                DatePrecision.RANGE,
            ),
            (
                {"date_precision": "exact", "start_stage": "2026-10-04", "end_stage": "2026-10-04"},
                DatePrecision.EXACT,
            ),
            (
                {"date_precision": "until", "start_stage": None, "end_stage": "2026-11-18"},
                DatePrecision.UNTIL,
            ),
            (
                {"date_precision": "unknown", "start_stage": None, "end_stage": None},
                DatePrecision.UNKNOWN,
            ),
        ],
    )
    def test_closes(self, payload, expected):
        assert date_precision(make_stage(payload)) is expected

    def test_one_day_range_becomes_a_circle(self):
        payload = {
            "date_precision": "range",
            "start_stage": "2026-10-04",
            "end_stage": "2026-10-04",
        }
        assert date_precision(make_stage(payload)) is DatePrecision.EXACT

    def test_month_precision_is_not_drawable(self):
        """Точность до месяца на сетке дней не изобразить."""
        stage = Stage(external_key="k", name="Этап")
        stage.starts_on = date(2027, 3, 1)
        stage.start_precision = Precision.MONTH
        stage.ends_on = None
        stage.end_precision = None
        assert date_precision(stage) is DatePrecision.UNKNOWN


class TestStageExternalKey:
    def test_normalizes_name(self):
        assert stage_external_key("  Дистанционный   ЭТАП ", set()) == "дистанционный этап"

    def test_duplicates_get_suffixes(self):
        taken = set()
        first = stage_external_key("Очный тур", taken)
        taken.add(first)
        second = stage_external_key("Очный тур", taken)
        assert first != second
        assert second.startswith("очный тур")

    def test_empty_name_still_gives_a_key(self):
        assert stage_external_key("", set()) == "stage"


class TestActivityIndex:
    def test_maps_activity_id_to_external_id(self):
        catalog = {
            "subjects": [
                {
                    "name": "Астрономия",
                    "olympiads": [
                        {"name": "МОШ", "id": "576", "activity_id": 99},
                        {"name": "СПб", "id": "631", "activity_id": 287},
                    ],
                }
            ]
        }
        assert build_activity_index(catalog) == {99: ["576"], 287: ["631"]}

    def test_same_activity_on_two_olympiads_keeps_both(self):
        """В каталоге такие пары есть — терять вторую нельзя."""
        catalog = {
            "subjects": [
                {
                    "name": "X",
                    "olympiads": [
                        {"name": "Первая", "id": "227", "activity_id": 5430},
                        {"name": "Вторая", "id": "443", "activity_id": 5430},
                    ],
                }
            ]
        }
        assert build_activity_index(catalog) == {5430: ["227", "443"]}

    def test_one_olympiad_under_many_subjects_is_not_a_duplicate(self):
        catalog = {
            "subjects": [
                {"name": "Физика", "olympiads": [{"id": "576", "activity_id": 99}]},
                {"name": "Математика", "olympiads": [{"id": "576", "activity_id": 99}]},
            ]
        }
        assert build_activity_index(catalog) == {99: ["576"]}

    @pytest.mark.parametrize(
        "olympiad",
        [
            {"name": "Без id", "activity_id": 99},
            {"name": "Без activity", "id": "576"},
            {"name": "Кривой activity", "id": "576", "activity_id": "не число"},
        ],
    )
    def test_incomplete_records_are_skipped(self, olympiad):
        catalog = {"subjects": [{"name": "X", "olympiads": [olympiad]}]}
        assert build_activity_index(catalog) == {}

    def test_empty_catalog_is_not_an_error(self):
        assert build_activity_index({}) == {}
