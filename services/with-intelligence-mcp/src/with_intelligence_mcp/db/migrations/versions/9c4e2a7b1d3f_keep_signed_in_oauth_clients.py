from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c4e2a7b1d3f"
down_revision: str | Sequence[str] | None = "7dab073eb40c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_auth_oauth_clients",
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # A client holding tokens has signed in. Without this, the first sweep after the upgrade
    # would still delete it once those tokens age out.
    op.execute(
        """
        UPDATE mcp_auth_oauth_clients
        SET activated_at = created_at
        WHERE client_id IN (SELECT client_id FROM mcp_auth_oauth_tokens)
        """
    )


def downgrade() -> None:
    op.drop_column("mcp_auth_oauth_clients", "activated_at")
