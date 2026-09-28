"""Тесты разбора дат парсером расписаний.

    pip install -r requirements.txt pytest
    python -m pytest test_olympiad_schedule_parser.py

Года в строке источника нет, парсер его угадывает — поэтому каждый
случай проверяется от заданного «сегодня».
"""

from datetime import datetime

import pytest

from olympiad_schedule_parser import parse_date_text

SEPTEMBER = datetime(2026, 9, 26)


def dates(raw, now=SEPTEMBER):
    parsed = parse_date_text(raw, now=now)
    return parsed["date_precision"], parsed["start_stage"], parsed["end_stage"]


class TestRangeAcrossMonths:
    def test_range_holding_current_month_stays_in_one_year(self):
        """Раньше начало уезжало в следующий год: 2027-08-20 … 2026-09-22."""
        assert dates("20 авг...22 сен") == ("range", "2026-08-20", "2026-09-22")

    def test_range_ahead_in_this_year(self):
        assert dates("5 ноя...11 дек") == ("range", "2026-11-05", "2026-12-11")

    def test_range_across_new_year(self):
        assert dates("15 дек...20 янв") == ("range", "2026-12-15", "2027-01-20")

    def test_range_after_new_year(self):
        assert dates("10 фев...3 мар") == ("range", "2027-02-10", "2027-03-03")

    def test_range_already_over_goes_to_next_year(self):
        """В октябре «20 авг...22 сен» — это уже следующий учебный год."""
        assert dates("20 авг...22 сен", now=datetime(2026, 10, 5)) == (
            "range", "2027-08-20", "2027-09-22",
        )

    @pytest.mark.parametrize("month", range(1, 13))
    def test_start_never_after_end(self, month):
        for raw in ("20 авг...22 сен", "15 дек...20 янв", "5 ноя...11 дек", "28 фев...2 мар"):
            _, start, end = dates(raw, now=datetime(2026, month, 15))
            assert start <= end, (raw, month)


class TestOtherForms:
    def test_range_inside_month(self):
        assert dates("4...17 дек") == ("range", "2026-12-04", "2026-12-17")

    def test_until(self):
        assert dates("до 22 окт") == ("until", None, "2026-10-22")

    def test_exact(self):
        assert dates("22 окт") == ("exact", "2026-10-22", "2026-10-22")

    def test_earlier_month_is_next_year(self):
        assert dates("14 мар") == ("exact", "2027-03-14", "2027-03-14")

    def test_unknown(self):
        assert dates("Уточняется") == ("unknown", None, None)
