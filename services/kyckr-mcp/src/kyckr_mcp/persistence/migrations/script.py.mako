## mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00
<% summary = (message or "Migration").rstrip(".!?") %>\
"""${summary[:1].upper() + summary[1:]}.

Revision ID: ${up_revision}
% if down_revision:
Revises: ${down_revision | comma,n}
% else:
Revises: none, the first revision
% endif
Create Date: ${create_date}
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
