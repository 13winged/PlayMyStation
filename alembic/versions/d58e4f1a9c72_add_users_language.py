"""Add users.language for RU/EN localization.

Revision ID: d58e4f1a9c72
Revises: c41f2e9a7b30
Create Date: 2026-09-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d58e4f1a9c72"
down_revision: Union[str, Sequence[str], None] = "c41f2e9a7b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("language", sa.String(length=5), server_default="ru"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "language")
