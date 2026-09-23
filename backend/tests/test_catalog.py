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
from app.catalog.presentation import (
    StageStatus,
    days_until_start,
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
