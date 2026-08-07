"""add login attempts

Revision ID: b2c3d4e5f6a7
Revises: 0be78700d2dc
Create Date: 2026-08-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "0be78700d2dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("source_ip", sa.String(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # The throttle read is `WHERE username = ? AND attempted_at >= ?`, so the composite index
    # serves it directly; `attempted_at` alone serves the cleanup sweep's range delete.
    op.create_index(
        "ix_login_attempts_username_attempted_at",
        "login_attempts",
        ["username", "attempted_at"],
    )
    op.create_index("ix_login_attempts_attempted_at", "login_attempts", ["attempted_at"])


def downgrade() -> None:
    op.drop_index("ix_login_attempts_attempted_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_username_attempted_at", table_name="login_attempts")
    op.drop_table("login_attempts")
