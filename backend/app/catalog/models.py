"""Модели каталога олимпиад.

Данные здесь — производные от внешнего источника, но храним их у себя, а
не ходим за ними на каждый запрос. Причины две: источник бывает
недоступен, и приложение обязано работать на последних известных данных;
а ещё по требованиям трека у каждой записи должно быть видно, откуда она
и когда обновлялась.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.models import Base
from .dates import Precision


class StageKind(str, Enum):
    """Тип этапа.

    Источник не размечает этапы — тип определяется по названию, поэтому
    это предположение, а не факт из первоисточника. ``OTHER`` означает,
    что уверенно определить не удалось.
    """

    REGISTRATION = "registration"
    QUALIFYING = "qualifying"
    FINAL = "final"
    OTHER = "other"


def _enum_column(enum_cls, type_name: str, **kwargs):
    """Хранит значения перечисления строками, а не именами Python.

    Имя типа задаётся явно: по умолчанию SQLAlchemy выводит его из имени
    класса, и `Precision` превратился бы в тип `precision` — а это
    зарезервированное слово Postgres (`DOUBLE PRECISION`), на котором
    падает CREATE TABLE.
    """
    return mapped_column(
        SAEnum(
            enum_cls,
            name=type_name,
            values_callable=lambda cls: [item.value for item in cls],
        ),
        **kwargs,
    )


class Category(Base):
    """Категория или подкатегория — одно дерево.

    Часть категорий имеет подкатегории, часть ведёт сразу к предметам;
    самоссылка позволяет описать оба случая одной таблицей.
    """

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    children: Mapped[List["Category"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    parent: Mapped[Optional["Category"]] = relationship(
        back_populates="children", remote_side=[id]
    )
    subjects: Mapped[List["Subject"]] = relationship(back_populates="category")


class Subject(Base):
    """Предмет олимпиады.

    Несёт цвет для карточек и короткий код: в режиме для дальтоников
    интерфейс показывает «МАТ» вместо одного лишь цветного кружка.
    """

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    color: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    short_code: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )

    category: Mapped[Optional[Category]] = relationship(back_populates="subjects")
    olympiads: Mapped[List["Olympiad"]] = relationship(back_populates="subject")


class Olympiad(Base):
    """Олимпиада по конкретному предмету.

    Одна запись — это пара «олимпиада + предмет», а не олимпиада целиком.
    Так сделано потому, что уровень по перечню РСОШ зависит от предмета:
    Московская олимпиада по астрономии — I уровня, по биологии — II.
    Интерфейс тоже всегда показывает олимпиаду внутри предмета, с
    предметом и уровнем на карточке.

    Следствие: «Олимпиада СПбГУ» присутствует четырнадцать раз, по разу
    на предмет, и добавляется в «Мои олимпиады» тоже по предмету.
    """

    __tablename__ = "olympiads"
    __table_args__ = (
        # Устойчивый ключ записи: идентификатор олимпиады в источнике
        # плюс предмет. Позволяет обновлять данные, не пересоздавая
        # строки, на которые ссылается прогресс пользователя.
        UniqueConstraint(
            "source", "external_id", "subject_id", name="uq_olympiad_source_key"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Откуда запись и когда её последний раз видели в источнике —
    # без этого нельзя показать пользователю дату актуальности.
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="postupi.online")
    # Идентификатор олимпиады в источнике. У выгрузки парсера его нет —
    # там запись опознаётся по ссылке.
    external_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Ссылка на страницу источника. Есть не у всех источников.
    source_url: Mapped[Optional[str]] = mapped_column(
        String(1024), unique=True, nullable=True
    )
    source_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)

    subject_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True
    )
    level: Mapped[Optional[int]] = mapped_column(
        SmallInteger,
        nullable=True,
        doc="Уровень по перечню РСОШ для этого предмета: 1, 2 или 3",
    )
    # По одному предмету олимпиада иногда проходит сразу на нескольких
    # уровнях. `level` тогда хранит лучший из них — для сортировки, —
    # а полный список остаётся здесь, чтобы показать «II–III ур.».
    levels: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # Классы участников строкой источника: «7-11 классы» или пустое,
    # если источник их не знает. Показывается как есть.
    grades: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Та же строка, разобранная в границы: по тексту не отфильтруешь, а
    # подбор олимпиад под класс пользователя — основа вкладки «Поиск».
    grade_min: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    grade_max: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    official_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    # Организаторы: список коротких названий, не больше трёх. Это не
    # вузы, засчитывающие олимпиаду, — те лежат в partner_universities.
    organizers: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Вузы, засчитывающие олимпиаду. Это не организаторы — не путать.
    partner_universities: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    subject: Mapped[Optional[Subject]] = relationship(back_populates="olympiads")
    stages: Mapped[List["Stage"]] = relationship(
        back_populates="olympiad",
        cascade="all, delete-orphan",
        order_by="Stage.position",
    )

    def __repr__(self) -> str:  # pragma: no cover - отладочное представление
        return f"<Olympiad id={self.id} name={self.name[:40]!r}>"


class Stage(Base):
    """Этап олимпиады.

    Даты хранятся вместе с точностью: у трети этапов источник знает только
    месяц. Всё, что считает дни — таймеры, календарь, напоминания, —
    обязано проверять точность, иначе покажет выдуманное число.
    """

    __tablename__ = "stages"
    __table_args__ = (
        # Устойчивый ключ этапа внутри олимпиады: позволяет обновлять
        # данные из источника, не пересоздавая строки. Иначе прогресс
        # пользователя («прошёл / не прошёл») терял бы привязку.
        UniqueConstraint("olympiad_id", "external_key", name="uq_stage_external_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    olympiad_id: Mapped[int] = mapped_column(
        ForeignKey("olympiads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_key: Mapped[str] = mapped_column(String(255), nullable=False)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[StageKind] = _enum_column(
        StageKind, "stage_kind", nullable=False, default=StageKind.OTHER
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    starts_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    start_precision: Mapped[Optional[Precision]] = _enum_column(
        Precision, "date_precision", nullable=True
    )
    ends_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    end_precision: Mapped[Optional[Precision]] = _enum_column(
        Precision, "date_precision", nullable=True
    )

    # Исходная строка источника — показываем её, когда точности не хватает
    # на таймер: «март 2027» честнее, чем вычисленное «через 154 дня».
    raw_date_range: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    source_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    olympiad: Mapped[Olympiad] = relationship(back_populates="stages")

    @property
    def has_exact_start(self) -> bool:
        return self.start_precision is Precision.DAY

    def __repr__(self) -> str:  # pragma: no cover - отладочное представление
        return f"<Stage id={self.id} kind={self.kind} name={self.name[:30]!r}>"
