"""create oauth, session and login-attempt tables

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-09-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "with_intelligence_sessions",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("wi_username", sa.String(), nullable=False),
        sa.Column("encrypted_blob", sa.LargeBinary(), nullable=False),
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
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        op.f("ix_with_intelligence_sessions_wi_username"),
        "with_intelligence_sessions",
        ["wi_username"],
        unique=True,
    )
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("client_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("client_id"),
    )
    op.create_table(
        "authorization_codes",
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("code_challenge", sa.String(), nullable=False),
        sa.Column("redirect_uri", sa.String(), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("resource", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.client_id"]),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_index(
        op.f("ix_authorization_codes_subject"), "authorization_codes", ["subject"], unique=False
    )
    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("access_token_hash", sa.String(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(), nullable=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("resource", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_from", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.client_id"]),
        sa.ForeignKeyConstraint(["rotated_from"], ["oauth_tokens.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_oauth_tokens_access_token_hash"),
        "oauth_tokens",
        ["access_token_hash"],
        unique=True,
    )
    op.create_index(op.f("ix_oauth_tokens_family_id"), "oauth_tokens", ["family_id"], unique=False)
    op.create_index(
        op.f("ix_oauth_tokens_refresh_token_hash"),
        "oauth_tokens",
        ["refresh_token_hash"],
        unique=True,
    )
    op.create_index(op.f("ix_oauth_tokens_subject"), "oauth_tokens", ["subject"], unique=False)
    op.create_table(
        "pending_authorizations",
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("code_challenge", sa.String(), nullable=False),
        sa.Column("redirect_uri", sa.String(), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("resource", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.client_id"]),
        sa.PrimaryKeyConstraint("request_id"),
    )
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
    op.drop_table("pending_authorizations")
    op.drop_index(op.f("ix_oauth_tokens_subject"), table_name="oauth_tokens")
    op.drop_index(op.f("ix_oauth_tokens_refresh_token_hash"), table_name="oauth_tokens")
    op.drop_index(op.f("ix_oauth_tokens_family_id"), table_name="oauth_tokens")
    op.drop_index(op.f("ix_oauth_tokens_access_token_hash"), table_name="oauth_tokens")
    op.drop_table("oauth_tokens")
    op.drop_index(op.f("ix_authorization_codes_subject"), table_name="authorization_codes")
    op.drop_table("authorization_codes")
    op.drop_table("oauth_clients")
    op.drop_index(
        op.f("ix_with_intelligence_sessions_wi_username"),
        table_name="with_intelligence_sessions",
    )
    op.drop_table("with_intelligence_sessions")
