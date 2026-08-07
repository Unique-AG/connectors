"""Key custom-field schema snapshots by caller subject.

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-08-07 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Snapshots are a cache — drop and recreate rather than inventing a subject for old rows.
    op.drop_table("custom_field_schema_snapshots")
    op.create_table(
        "custom_field_schema_snapshots",
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("base_url", "subject"),
    )


def downgrade() -> None:
    op.drop_table("custom_field_schema_snapshots")
    op.create_table(
        "custom_field_schema_snapshots",
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("base_url"),
    )
