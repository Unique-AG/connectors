"""Search-path activity types shared by the search tool and `SearchActivitiesQuery`.

These cannot live on the query — the tool names them on its published parameter, and the
query file is the `POST /entity-activities` walker, not the vocabulary. Each token is also
the `newFilters.types` search value Backstop matches.
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
