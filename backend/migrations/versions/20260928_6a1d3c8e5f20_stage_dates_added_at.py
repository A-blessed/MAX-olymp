"""stage dates added at

Момент, когда у этапа появились даты. Нужен блоку «Появились даты» в
новостях: этапы обновляются на месте, и без отметки нельзя узнать, что
дат раньше не было. У уже существующих этапов отметки нет — иначе после
миграции все они разом «появились» бы в новостях.

Revision ID: 6a1d3c8e5f20
Revises: 4f7c2a9e1b3d
Create Date: 2026-09-28 12:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '6a1d3c8e5f20'
down_revision: Union[str, None] = '4f7c2a9e1b3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('stages', sa.Column('dates_added_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('stages', 'dates_added_at')
