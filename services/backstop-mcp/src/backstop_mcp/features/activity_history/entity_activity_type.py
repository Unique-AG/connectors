"""Search-path activity types shared by the search tool and `SearchActivitiesQuery`.

These cannot live on the query — the tool names them on its published parameter, and the
query file is the undocumented POST walker, not the vocabulary.
"""

from typing import Literal

type EntityActivityType = Literal[
    "meeting_call", "meeting", "document", "email", "email_blast", "note"
]
ENTITY_ACTIVITY_TYPES: tuple[EntityActivityType, ...] = (
    "meeting_call",
    "meeting",
    "document",
    "email",
    "email_blast",
    "note",
)
