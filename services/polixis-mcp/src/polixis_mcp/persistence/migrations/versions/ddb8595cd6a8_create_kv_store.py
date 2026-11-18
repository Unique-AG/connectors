"""Create kv_store.

Revision ID: ddb8595cd6a8
Revises: e42d5cef53e2
Create Date: 2026-11-18 13:29:23.349065

The key-value store made this table itself on first use before, so a database from then
already has it, with the same columns and index, and keeps its rows.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "ddb8595cd6a8"
down_revision: str | Sequence[str] | None = "e42d5cef53e2"
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


def downgrade() -> None:
    op.drop_index(
        "idx_kv_store_expires_at",
        table_name="kv_store",
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.drop_table("kv_store")
