"""Initial migration: users + integrations tables

Revision ID: 771b2df7f38b
Revises:
Create Date: 2026-09-25 15:47:59.674751

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '771b2df7f38b'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('active_provider', sa.String(length=20), nullable=False, server_default='all'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id', name='users_pkey'),
        sa.UniqueConstraint('telegram_id', name='users_telegram_id_key'),
    )
    op.create_index('ix_users_telegram_id', 'users', ['telegram_id'], unique=False)

    op.create_table(
        'integrations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('access_token', sa.Text(), nullable=True),
        sa.Column('refresh_token', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('service_user_id', sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE', name='integrations_user_id_fkey'),
        sa.PrimaryKeyConstraint('id', name='integrations_pkey'),
        sa.UniqueConstraint('user_id', 'provider', name='uq_user_provider'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('integrations')
    op.drop_index('ix_users_telegram_id', table_name='users')
    op.drop_table('users')