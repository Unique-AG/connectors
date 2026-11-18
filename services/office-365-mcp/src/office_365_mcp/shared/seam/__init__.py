"""Where the shared vocabulary meets FastMCP: the only part of `shared/` that imports it.

Each module is one concern. Tools import the names from this package, not from its modules.
"""

from office_365_mcp.shared.seam.advice import (
    Advised,
    GraphAdviceMiddleware,
    ToolAdvice,
    narrowed_to,
    owner_refused,
)
from office_365_mcp.shared.seam.annotations import (
    READ_ONLY,
    WRITE_ADDITIVE,
    WRITE_DESTRUCTIVE,
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    WRITE_IDEMPOTENT,
)
from office_365_mcp.shared.seam.caller import (
    MAILBOX_FIELD,
    GraphToken,
    TokenExchangeFailed,
    graph_client_for_caller,
    graph_mailbox,
)
from office_365_mcp.shared.seam.elicitation import (
    Confirm,
    Confirmed,
    DigestPart,
    answer_pending,
    confirmation_digest,
    person_confirms,
)
from office_365_mcp.shared.seam.files import FileFromGraph
from office_365_mcp.shared.seam.permissions import REQUESTABLE_PERMISSIONS, graph_scope

__all__ = [
    "MAILBOX_FIELD",
    "READ_ONLY",
    "REQUESTABLE_PERMISSIONS",
    "WRITE_ADDITIVE",
    "WRITE_DESTRUCTIVE",
    "WRITE_DESTRUCTIVE_IDEMPOTENT",
    "WRITE_IDEMPOTENT",
    "Advised",
    "Confirm",
    "Confirmed",
    "DigestPart",
    "FileFromGraph",
    "GraphAdviceMiddleware",
    "GraphToken",
    "TokenExchangeFailed",
    "ToolAdvice",
    "answer_pending",
    "confirmation_digest",
    "graph_client_for_caller",
    "graph_mailbox",
    "graph_scope",
    "narrowed_to",
    "owner_refused",
    "person_confirms",
]
