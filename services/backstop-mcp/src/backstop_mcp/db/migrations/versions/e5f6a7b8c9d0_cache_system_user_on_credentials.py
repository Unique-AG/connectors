"""cache system user on backstop credentials

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "backstop_credentials",
        sa.Column("external_user_id", sa.String(), nullable=True),
    )
    op.add_column(
        "backstop_credentials",
        sa.Column("raw", JSONB(), nullable=True),
    )
    op.create_index(
        op.f("ix_backstop_credentials_external_user_id"),
        "backstop_credentials",
        ["external_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_backstop_credentials_external_user_id"),
        table_name="backstop_credentials",
    )
    op.drop_column("backstop_credentials", "raw")
    op.drop_column("backstop_credentials", "external_user_id")
