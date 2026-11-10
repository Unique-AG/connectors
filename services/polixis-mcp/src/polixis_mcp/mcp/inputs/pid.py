from typing import Annotated

from pydantic import Field

# A letter for the kind of entity and 32 hex digits. Checked here so a malformed pid fails
# before it spends a request of the Polixis quota.
PID_PATTERN = r"^[POUpou][0-9a-fA-F]{32}$"

EntityPid = Annotated[
    str | None,
    Field(
        pattern=PID_PATTERN,
        description=(
            "The entity's pid, from `search_entities`, or one the user gave once "
            "`resolve_permanent_id` confirmed it. Required unless `cursor` is."
        ),
    ),
]
