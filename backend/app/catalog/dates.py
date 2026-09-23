"""Разбор дат этапов олимпиад.

Источник отдаёт даты строками разной точности:

    "17 сен 2026"   — известен день
    "мар 2027"      — известен только месяц
    ""              — даты нет

Разница принципиальная. Механика приложения считает «до этапа N дней»,
строит календарь по дням и шлёт напоминания за час до начала — всё это
возможно только для дат с точностью до дня. Для этапа, о котором известен
лишь месяц, такой расчёт дал бы правдоподобное, но выдуманное число.

Поэтому дата всегда хранится вместе с признаком точности, а всё, что
зависит от конкретного дня, обязано этот признак проверять.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional, Tuple


class Precision(str, Enum):
    """Насколько точно известна дата."""

    DAY = "day"
    MONTH = "month"

    @property
    def is_exact(self) -> bool:
        return self is Precision.DAY


# Первые три буквы однозначно определяют месяц во всех формах, которые
# встречаются на сайте: сокращение («сен»), именительный падеж
# («сентябрь») и родительный («сентября»). Исключение — «мая», у которого
# первые три буквы отличаются от «май».
_MONTH_BY_PREFIX = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "май": 5,
    "мая": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}

# Разделители диапазона: длинное тире, короткое, дефис.
_RANGE_SPLIT = re.compile(r"\s+[—–-]\s+")

_DAY_MONTH_YEAR = re.compile(r"^(\d{1,2})\s+([^\s\d]+)\s+(\d{4})$")
_MONTH_YEAR = re.compile(r"^([^\s\d]+)\s+(\d{4})$")


@dataclass(frozen=True)
class ParsedDate:
    """Дата этапа вместе с точностью и исходной строкой."""

    value: date
    precision: Precision
    raw: str

    @property
    def is_exact(self) -> bool:
        return self.precision.is_exact


def _month_number(token: str) -> Optional[int]:
    normalized = token.strip().lower().replace("ё", "е").rstrip(".")
    return _MONTH_BY_PREFIX.get(normalized[:3])


def parse_date(raw: str) -> Optional[ParsedDate]:
    """Разбирает одну дату. Возвращает ``None``, если строка пустая или чужая.

    Для точности ``MONTH`` днём подставляется первое число — это позволяет
    сортировать такие этапы вместе с остальными, но выводить их в
    интерфейсе можно только как «март 2027».
    """
    if not raw:
        return None

    text = re.sub(r"\s+", " ", raw.replace("\xa0", " ")).strip()
    if not text:
        return None

    match = _DAY_MONTH_YEAR.match(text)
    if match:
        day, month_token, year = match.groups()
        month = _month_number(month_token)
        if month is None:
            return None
        try:
            return ParsedDate(date(int(year), month, int(day)), Precision.DAY, text)
        except ValueError:
            # Например «31 фев 2027» — в источнике встречаются опечатки.
            return None

    match = _MONTH_YEAR.match(text)
    if match:
        month_token, year = match.groups()
        month = _month_number(month_token)
        if month is None:
            return None
        return ParsedDate(date(int(year), month, 1), Precision.MONTH, text)

    return None


def parse_range(raw: str) -> Tuple[Optional[ParsedDate], Optional[ParsedDate]]:
    """Разбирает «17 сен 2026 — 23 окт 2026» на начало и конец.

    Одиночная дата считается началом без конца.
    """
    if not raw:
        return None, None

    text = re.sub(r"\s+", " ", raw.replace("\xa0", " ")).strip()
    if not text:
        return None, None

    parts = _RANGE_SPLIT.split(text, maxsplit=1)
    start = parse_date(parts[0])
    end = parse_date(parts[1]) if len(parts) == 2 else None
    return start, end


def days_until(target: ParsedDate, today: Optional[date] = None) -> Optional[int]:
    """Сколько дней осталось до даты. ``None``, если день неизвестен.

    Возврат ``None`` — не ошибка, а единственный честный ответ для этапа,
    о котором известен только месяц. Вызывающий код должен показать
    «март 2027» вместо таймера, а не подставлять ноль.
    """
    if not target.is_exact:
        return None
    return (target.value - (today or date.today())).days
