"""Drop polixis_response_cache.reads, which nothing read.

Revision ID: 9c1e4b7a2d30
Revises: 67402c459b5b
Create Date: 2026-11-18 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "9c1e4b7a2d30"
down_revision: str | Sequence[str] | None = "67402c459b5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("polixis_response_cache", "reads")


def downgrade() -> None:
    op.add_column(
        "polixis_response_cache",
        sa.Column("reads", sa.Integer(), server_default="0", nullable=False),
    )
