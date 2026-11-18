from datetime import datetime
from datetime import UTC

from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import Field

from polixis_mcp.upstream import oldest_cache_read


class Freshness(BaseModel):
    """Computed by this MCP: when this result was put together, and whether any of its data came
    from this server's cache of Polixis's answers rather than from Polixis on this call.
    """

    fetched_at: AwareDatetime = Field(description="When this server put this result together.")
    cached_at: AwareDatetime | None = Field(
        description=(
            "Null when all of this result came from Polixis on this call. Otherwise some or all "
            "of it came from this server's cache, and this is when Polixis's answer was cached, "
            "the oldest one when several were: the data is as of then. When its age matters, as "
            "for sanctions or PEP status, tell the user the data is as of this time."
        )
    )


def freshness() -> Freshness:
    """The freshness of the result the current tool call is putting together."""
    return Freshness(fetched_at=datetime.now(UTC), cached_at=oldest_cache_read())
