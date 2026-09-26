"""Replace soundcloud with youtube provider.

Revision ID: c41f2e9a7b30
Revises: 771b2df7f38b
Create Date: 2026-09-26

SoundCloud-привязки не мигрируются (там OAuth-токены SoundCloud,
для YouTube Music нужен browser-auth через ytmusicapi) — удаляем их,
юзерам нужно перепривязать YouTube через /youtube.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c41f2e9a7b30"
down_revision: Union[str, Sequence[str], None] = "771b2df7f38b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(sa.text("DELETE FROM integrations WHERE provider = 'soundcloud'"))
    op.execute(sa.text("UPDATE users SET active_provider = 'all' WHERE active_provider = 'soundcloud'"))


def downgrade() -> None:
    """Downgrade schema (интеграции не восстанавливаются — нужен ре-auth)."""
    op.execute(sa.text("UPDATE users SET active_provider = 'all' WHERE active_provider = 'soundcloud'"))
