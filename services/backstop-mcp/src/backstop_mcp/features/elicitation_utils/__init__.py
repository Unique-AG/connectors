"""Shared MCP elicitation helpers that are not name-resolution.

`elicit_entity_deletion` asks the user to confirm a hard delete and returns
what the tool should return: `InputRequiredResult` (2026-07-28 form),
`DeletionNeedsConfirmationResponse` (handshake-era chat retry with
`confirm=true`), or `None` so the tool deletes. A decline raises. Tools pass a
prompt string or an async callback that builds one after a confirm is known to
be needed.
"""

from backstop_mcp.features.elicitation_utils.elicit_entity_deletion import (
    CONFIRM_FIELD_DESCRIPTION,
    DELETE,
    DELETION_INPUT_KEY,
    DELETION_NOT_CONFIRMED,
    KEEP,
    REFUSE_BULK_DELETE,
    DeletionChoice,
    DeletionElicitResult,
    elicit_entity_deletion,
)
from backstop_mcp.features.elicitation_utils.responses import (
    CONFIRM_RETRY_MESSAGE,
    DeletionNeedsConfirmationResponse,
)

__all__ = [
    "CONFIRM_FIELD_DESCRIPTION",
    "CONFIRM_RETRY_MESSAGE",
    "DELETE",
    "DELETION_INPUT_KEY",
    "DELETION_NOT_CONFIRMED",
    "KEEP",
    "REFUSE_BULK_DELETE",
    "DeletionChoice",
    "DeletionElicitResult",
    "DeletionNeedsConfirmationResponse",
    "elicit_entity_deletion",
]
