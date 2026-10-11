"""Phase 7: Add user notification and summary settings columns

Revision ID: 002_phase7
Revises: 001_initial
Create Date: 2026-10-11 12:16:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002_phase7"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}

    if "reminders_enabled" not in columns:
        op.add_column(
            "users",
            sa.Column("reminders_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        )
    if "daily_summary_enabled" not in columns:
        op.add_column(
            "users",
            sa.Column("daily_summary_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        )
    if "daily_summary_time" not in columns:
        op.add_column(
            "users",
            sa.Column("daily_summary_time", sa.String(length=5), nullable=False, server_default="09:00"),
        )
    if "last_summary_date" not in columns:
        op.add_column(
            "users",
            sa.Column("last_summary_date", sa.String(length=10), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("last_summary_date")
        batch_op.drop_column("daily_summary_time")
        batch_op.drop_column("daily_summary_enabled")
        batch_op.drop_column("reminders_enabled")
