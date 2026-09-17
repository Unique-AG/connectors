"""Shared MCP elicitation helpers that are not name-resolution.

`elicit_entity_deletion` asks the user to confirm a hard delete and classifies the
answer as `CONFIRMED`, `DECLINED`, or `NOT_AVAILABLE` when the client never advertised
elicitation. Tools pass a prompt string or an async callback that builds one only after
the client is known to be able to show the form.
"""

from backstop_mcp.features.elicitation_utils.elicit_entity_deletion import (
    DELETE,
    DELETION_NOT_CONFIRMED,
    KEEP,
    REFUSE_BULK_DELETE,
    DeletionChoice,
    EntityDeletion,
    elicit_entity_deletion,
)

__all__ = [
    "DELETE",
    "DELETION_NOT_CONFIRMED",
    "KEEP",
    "REFUSE_BULK_DELETE",
    "DeletionChoice",
    "EntityDeletion",
    "elicit_entity_deletion",
]
