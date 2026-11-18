"""Create polixis_response_cache.

Revision ID: e42d5cef53e2
Revises: none, the first revision
Create Date: 2026-11-18 13:09:20.996014
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "e42d5cef53e2"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "polixis_response_cache",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column(
            "size_bytes",
            sa.Integer(),
            sa.Computed("octet_length(body)", persisted=True),
            nullable=False,
        ),
        sa.Column("cached_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reads", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("polixis_response_cache")
