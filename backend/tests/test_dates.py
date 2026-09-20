"""Тесты разбора дат этапов.

Формы месяцев взяты из реальной выгрузки: там соседствуют сокращения
(«сен», «мар») и полные названия в родительном падеже («июня», «июля»).
Реализация, знающая только один вариант, тихо теряет часть этапов.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.catalog.dates import Precision, days_until, parse_date, parse_range


class TestParseDate:
    def test_exact_date(self):
        result = parse_date("17 сен 2026")

        assert result is not None
        assert result.value == date(2026, 9, 17)
        assert result.precision is Precision.DAY
        assert result.is_exact

    def test_month_only(self):
        result = parse_date("мар 2027")

        assert result is not None
        assert result.value == date(2027, 3, 1)
        assert result.precision is Precision.MONTH
        assert not result.is_exact

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1 июня 2026", date(2026, 6, 1)),
            ("1 июля 2026", date(2026, 7, 1)),
            ("26 авг 2026", date(2026, 8, 26)),
            ("5 ноя 2026", date(2026, 11, 5)),
            ("11 дек 2026", date(2026, 12, 11)),
            ("15 фев 2027", date(2027, 2, 15)),
            ("2 янв 2027", date(2027, 1, 2)),
            ("21 апр 2026", date(2026, 4, 21)),
            ("9 мая 2027", date(2027, 5, 9)),
            ("1 октября 2026", date(2026, 10, 1)),
        ],
    )
    def test_month_forms(self, raw, expected):
        """Сокращения, родительный падеж и полные названия — всё должно читаться."""
        result = parse_date(raw)

        assert result is not None, f"не разобрано: {raw}"
        assert result.value == expected

    def test_non_breaking_spaces(self):
        """Источник отдаёт даты с NBSP: «17&nbsp;сен&nbsp;2026»."""
        result = parse_date("17\xa0сен\xa02026")

        assert result is not None
        assert result.value == date(2026, 9, 17)

    @pytest.mark.parametrize("raw", ["", "   ", "скоро", "2026", "32 сен 2026", "17 фвр 2026"])
    def test_unparseable_returns_none(self, raw):
        assert parse_date(raw) is None

    def test_impossible_date_is_rejected(self):
        """В источнике встречаются опечатки — падать на них нельзя."""
        assert parse_date("31 фев 2027") is None


class TestParseRange:
    def test_full_range(self):
        start, end = parse_range("17 сен 2026 — 23 окт 2026")

        assert start is not None and start.value == date(2026, 9, 17)
        assert end is not None and end.value == date(2026, 10, 23)

    def test_single_date_has_no_end(self):
        start, end = parse_range("мар 2027")

        assert start is not None and start.value == date(2027, 3, 1)
        assert end is None

    def test_month_range(self):
        start, end = parse_range("ноя 2026 — дек 2026")

        assert start is not None and start.precision is Precision.MONTH
        assert end is not None and end.precision is Precision.MONTH

    @pytest.mark.parametrize("dash", ["—", "–", "-"])
    def test_dash_variants(self, dash):
        start, end = parse_range(f"1 сен 2026 {dash} 30 ноя 2026")

        assert start is not None and end is not None

    def test_empty_range(self):
        assert parse_range("") == (None, None)


class TestDaysUntil:
    def test_counts_days_for_exact_date(self):
        target = parse_date("20 сен 2026")

        assert target is not None
        assert days_until(target, today=date(2026, 9, 15)) == 5

    def test_returns_none_for_month_precision(self):
        """Для этапа «март 2027» честный ответ — «неизвестно», а не число.

        Иначе интерфейс покажет таймер, посчитанный от первого числа
        месяца, которого в источнике нет.
        """
        target = parse_date("мар 2027")

        assert target is not None
        assert days_until(target, today=date(2026, 9, 15)) is None

    def test_past_date_is_negative(self):
        target = parse_date("1 сен 2026")

        assert target is not None
        assert days_until(target, today=date(2026, 9, 15)) == -14
