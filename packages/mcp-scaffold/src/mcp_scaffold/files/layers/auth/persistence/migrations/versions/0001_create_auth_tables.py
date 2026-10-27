"""Create the tables the sign-in keeps.

Revision ID: 0001_create_auth_tables
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_create_auth_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_auth_clients",
        sa.Column("client_id", sa.String(255), primary_key=True),
        sa.Column("registration", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_table(
        "mcp_auth_pending_sign_ins",
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column(
            "client_id",
            sa.String(255),
            sa.ForeignKey("mcp_auth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.String(255), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Float(), nullable=False, index=True),
    )
    op.create_table(
        "mcp_auth_authorization_codes",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column(
            "client_id",
            sa.String(255),
            sa.ForeignKey("mcp_auth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.String(255), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("subject", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False, index=True),
    )
    op.create_table(
        "mcp_auth_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("family_id", sa.String(36), nullable=False, index=True),
        sa.Column("access_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "client_id",
            sa.String(255),
            sa.ForeignKey("mcp_auth_clients.client_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("subject", sa.String(36), nullable=False, index=True),
        sa.Column("access_token_expires_at", sa.Float(), nullable=False),
        sa.Column("refresh_token_expires_at", sa.Float(), nullable=False, index=True),
        sa.Column("revoked_at", sa.Float(), nullable=True),
    )
    op.create_table(
        "mcp_auth_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(320), nullable=False, unique=True),
        sa.Column("password", sa.Text(), nullable=False),
    )
    op.create_table(
        "mcp_auth_failed_sign_ins",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(320), nullable=False),
        sa.Column("at", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_mcp_auth_failed_sign_ins_username_at", "mcp_auth_failed_sign_ins", ["username", "at"]
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_auth_failed_sign_ins_username_at", "mcp_auth_failed_sign_ins")
    for table in [
        "mcp_auth_failed_sign_ins",
        "mcp_auth_credentials",
        "mcp_auth_tokens",
        "mcp_auth_authorization_codes",
        "mcp_auth_pending_sign_ins",
        "mcp_auth_clients",
    ]:
        op.drop_table(table)
