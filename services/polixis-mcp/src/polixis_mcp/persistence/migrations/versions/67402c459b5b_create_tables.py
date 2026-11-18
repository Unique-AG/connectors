"""Create kv_store and polixis_response_cache.

Revision ID: 67402c459b5b
Revises: none, the first revision
Create Date: 2026-11-18 16:20:00.000000

The key-value store made `kv_store` itself on first use before, so a database from then already
has it, with the same columns and index, and keeps its rows.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "67402c459b5b"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kv_store",
        sa.Column("collection", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("ttl", sa.Double[float](), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("collection", "key"),
        if_not_exists=True,
    )
    op.create_index(
        "idx_kv_store_expires_at",
        "kv_store",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("expires_at IS NOT NULL"),
        if_not_exists=True,
    )
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
    op.drop_index(
        "idx_kv_store_expires_at",
        table_name="kv_store",
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.drop_table("kv_store")
