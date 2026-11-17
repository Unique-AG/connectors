from typing import Annotated

from pydantic import Field

from polixis_mcp.contexts import PID_PATTERN

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
