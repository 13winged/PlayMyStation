"""Align users constraints with ORM without losing existing users."""

from alembic import op
import sqlalchemy as sa

revision = "f82c419a6b03"
down_revision = "e7a3c5d19f42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Старые записи могли содержать NULL: сначала восстанавливаем язык.
    op.execute("UPDATE users SET language = 'ru' WHERE language IS NULL")
    op.alter_column("users", "language", existing_type=sa.String(5), nullable=False)
    # Уникальность сохраняется старым constraint до создания нового индекса.
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)
    op.drop_constraint("users_telegram_id_key", "users", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("users_telegram_id_key", "users", ["telegram_id"])
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=False)
    op.alter_column("users", "language", existing_type=sa.String(5), nullable=True)
