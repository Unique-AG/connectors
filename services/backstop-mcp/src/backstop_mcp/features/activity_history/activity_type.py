"""Stream and party-collection aliases shared by the history query, responses, and paging.

They cannot live on `GetActivityHistoryQuery` — that file imports the published group models —
or in `internal_dto` (Dto classes only).
"""

from typing import Literal

from backstop_mcp.features.entity_types import SearchType

type BackstopActivityType = Literal["meeting", "call", "note", "document"]
type ActivityType = BackstopActivityType | Literal["email"]
# Same vocabulary as party resolve: person-scoped quick-search can return contacts/employees.
type Segment = SearchType
