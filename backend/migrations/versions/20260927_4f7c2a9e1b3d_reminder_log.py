"""reminder log

Журнал утренних сводок бота: одна строка на пользователя и день. Нужен,
чтобы после перезапуска бэкенда не написать человеку второй раз.

Revision ID: 4f7c2a9e1b3d
Revises: 8d8eddbae444
Create Date: 2026-09-27 12:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4f7c2a9e1b3d'
down_revision: Union[str, None] = '8d8eddbae444'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('reminder_log',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('sent_for', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('items', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'sent_for')
    )


def downgrade() -> None:
    op.drop_table('reminder_log')
