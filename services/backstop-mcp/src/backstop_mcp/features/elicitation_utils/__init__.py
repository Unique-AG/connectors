"""Shared MCP elicitation helpers that are not name-resolution.

`elicit_entity_deletion` asks the user to confirm a hard delete and returns
`CONFIRMED`, `NOT_AVAILABLE`, or `DECLINED`. Tools pass a prompt string or an
async callback that builds one after elicitation is known to be available;
this package only runs the elicit and classifies the answer.
"""

from backstop_mcp.features.elicitation_utils.elicit_entity_deletion import (
    DELETE,
    KEEP,
    DeletionChoice,
    EntityDeletion,
    elicit_entity_deletion,
)

__all__ = [
    "DELETE",
    "KEEP",
    "DeletionChoice",
    "EntityDeletion",
    "elicit_entity_deletion",
]
