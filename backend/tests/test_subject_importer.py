"""Тесты разбора файла олимпиад, сгруппированных по предметам.

Все случаи взяты из реального файла: римские уровни, список уровней по
одному предмету, «Нет информации» вместо классов и ключ организаторов,
записанный кириллицей.
"""

from __future__ import annotations

import pytest

from app.catalog.subject_importer import (
    KNOWN_KEYS,
    SUBJECT_CATALOG,
    parse_grades,
    parse_levels,
    pick_organizers,
)


class TestParseLevels:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("I", [1]),
            ("II", [2]),
            ("III", [3]),
            (["II", "III"], [2, 3]),
            (["III", "II"], [2, 3]),
            ("  ii  ", [2]),
            ("2", [2]),
        ],
    )
    def test_known_values(self, raw, expected):
        assert parse_levels(raw) == expected

    def test_list_is_sorted_so_best_level_is_first(self):
        """`level` берётся как levels[0], и это должен быть лучший уровень."""
        assert parse_levels(["III", "I"])[0] == 1

    @pytest.mark.parametrize("raw", [None, "", [], "неизвестно", "—"])
    def test_unparseable_gives_empty_list(self, raw):
        assert parse_levels(raw) == []

    def test_duplicates_collapse(self):
        assert parse_levels(["II", "II"]) == [2]


class TestParseGrades:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("7-11 классы", "7-11 классы"),
            ("9–11 классы", "9–11 классы"),
            ("  5-11   классы ", "5-11 классы"),
        ],
    )
    def test_keeps_real_values(self, raw, expected):
        assert parse_grades(raw) == expected

    @pytest.mark.parametrize("raw", ["Нет информации", "нет информации", "", None])
    def test_absence_becomes_none(self, raw):
        """«Нет информации» — это отсутствие данных, а не значение."""
        assert parse_grades(raw) is None

    def test_long_value_is_truncated_to_column_size(self):
        assert len(parse_grades("к" * 200)) == 64


class TestPickOrganizers:
    def test_reads_cyrillic_key(self):
        """В файле ключ называется «организаторы», а не organizers."""
        assert pick_organizers({"организаторы": "МГУ"}) == "МГУ"

    def test_reads_latin_key_too(self):
        assert pick_organizers({"organizers": "МФТИ"}) == "МФТИ"

    def test_collapses_whitespace(self):
        assert pick_organizers({"организаторы": "МГУ;\n\n  СПбГУ"}) == "МГУ; СПбГУ"

    def test_missing_gives_none(self):
        assert pick_organizers({"name": "Олимпиада"}) is None


class TestSubjectCatalog:
    def test_ids_match_frontend_list(self):
        """Идентификаторы совпадают с SUBJECTS во фронтенде.

        Если они разойдутся, карточки покрасятся не в те цвета, а фильтр
        по предмету начнёт возвращать чужие олимпиады.
        """
        expected = [
            (1, "Астрономия"), (2, "Биология"), (3, "География"),
            (4, "Иностранный язык"), (5, "Информатика"), (6, "История"),
            (7, "Литература"), (8, "Математика"), (9, "Обществознание"),
            (10, "Право"), (11, "Русский язык"), (12, "Физика"),
            (13, "Химия"), (14, "Экономика"),
        ]

        assert [(item[0], item[2]) for item in SUBJECT_CATALOG] == expected

    def test_every_subject_has_colour_and_code(self):
        for _, slug, name, color, short_code in SUBJECT_CATALOG:
            assert color.startswith("#") and len(color) == 7, name
            assert short_code and len(short_code) <= 4, name
            assert slug and slug.isascii(), name

    def test_slugs_and_codes_are_unique(self):
        assert len({item[1] for item in SUBJECT_CATALOG}) == len(SUBJECT_CATALOG)
        assert len({item[4] for item in SUBJECT_CATALOG}) == len(SUBJECT_CATALOG)


def test_known_keys_cover_documented_format():
    """Поля сверх этого набора попадут в отчёт импорта как незнакомые.

    Так добавление дат в файл не пройдёт мимо: импорт сообщит о них.
    """
    assert {"name", "level", "grades", "official_url", "description", "id"} <= KNOWN_KEYS
    assert "registration_dates" not in KNOWN_KEYS
