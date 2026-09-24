"""organizers as list

Revision ID: 8d8eddbae444
Revises: b9b2e5434691
Create Date: 2026-09-24 18:19:39.414671
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '8d8eddbae444'
down_revision: Union[str, None] = 'b9b2e5434691'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Организаторы: одна строка -> список коротких названий.

    Колонка пересоздаётся, а не меняет тип: в ней лежит обычный текст
    вроде «МГУ, МФТИ», и привести его к JSONB нельзя — приведение
    упадёт на первой же строке.

    Терять тут нечего: каталог целиком собирается из файла источника,
    и данные возвращает повторный импорт.
    """
    op.drop_column("olympiads", "organizers")
    op.add_column(
        "olympiads",
        sa.Column(
            "organizers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("olympiads", "organizers")
    op.add_column("olympiads", sa.Column("organizers", sa.Text(), nullable=True))
