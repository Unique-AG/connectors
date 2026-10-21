"""Create positions.

Revision ID: 3c6e1f0a9b2d
Revises: none, the first revision
Create Date: 2026-10-21 15:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "3c6e1f0a9b2d"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "positions",
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("portfolio", sa.String(length=64), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("cost_basis", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("owner", "portfolio", "ticker"),
    )


def downgrade() -> None:
    op.drop_table("positions")
