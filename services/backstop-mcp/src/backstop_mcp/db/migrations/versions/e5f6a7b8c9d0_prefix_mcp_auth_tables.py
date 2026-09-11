from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_RENAMES = (
    ("oauth_clients", "mcp_auth_oauth_clients"),
    ("pending_authorizations", "mcp_auth_pending_authorizations"),
    ("authorization_codes", "mcp_auth_authorization_codes"),
    ("oauth_tokens", "mcp_auth_oauth_tokens"),
    ("login_attempts", "mcp_auth_login_attempts"),
)

INDEX_RENAMES = (
    ("ix_authorization_codes_subject", "ix_mcp_auth_authorization_codes_subject"),
    ("ix_oauth_tokens_access_token_hash", "ix_mcp_auth_oauth_tokens_access_token_hash"),
    ("ix_oauth_tokens_family_id", "ix_mcp_auth_oauth_tokens_family_id"),
    ("ix_oauth_tokens_refresh_token_hash", "ix_mcp_auth_oauth_tokens_refresh_token_hash"),
    ("ix_oauth_tokens_subject", "ix_mcp_auth_oauth_tokens_subject"),
    (
        "ix_login_attempts_username_attempted_at",
        "ix_mcp_auth_login_attempts_username_attempted_at",
    ),
    ("ix_login_attempts_attempted_at", "ix_mcp_auth_login_attempts_attempted_at"),
)


def _rename_index(old_name: str, new_name: str) -> None:
    op.execute(sa.text(f'ALTER INDEX "{old_name}" RENAME TO "{new_name}"'))


def upgrade() -> None:
    for old_name, new_name in TABLE_RENAMES:
        op.rename_table(old_name, new_name)
    for old_name, new_name in INDEX_RENAMES:
        _rename_index(old_name, new_name)


def downgrade() -> None:
    for old_name, new_name in reversed(INDEX_RENAMES):
        _rename_index(new_name, old_name)
    for old_name, new_name in reversed(TABLE_RENAMES):
        op.rename_table(new_name, old_name)
