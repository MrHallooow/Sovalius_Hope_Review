"""per-user notification read state

`notifications.read` is a single global flag, so one reviewer marking a
notification read hid it from every other reviewer on every desk. Read state
belongs to (notification, user); the legacy column is left in place for older
rows and tooling but is no longer what the API reports.

Revision ID: b7c41d2e9a05
Revises: 0ffacbda7518
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c41d2e9a05"
down_revision: Union[str, None] = "0ffacbda7518"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_reads",
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("notification_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("notification_reads")
