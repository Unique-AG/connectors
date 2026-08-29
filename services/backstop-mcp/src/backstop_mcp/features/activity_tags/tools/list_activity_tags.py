from typing import Annotated, Literal

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.activity_tags import (
    ActivityTagResponse,
    ActivityTagsService,
    get_activity_tags_service,
)


class ListActivityTagsResponse(BaseModel):
    """Activity tags from the standard Backstop activity-tag catalog."""

    status: Literal["ok"] = Field(default="ok", description="Always 'ok'.")
    cache: Literal["ok", "stale"] = Field(
        description=(
            "'ok' when the catalog was fetched this call or is still fresh; 'stale' when a "
            "previous catalog is served because refresh failed."
        )
    )
    tags: list[ActivityTagResponse] = Field(
        description=(
            "Activity tags in catalog order. Each tag's id is the stable identifier for "
            "filtering activities by tag. quantity_tagged is how many activities currently "
            "carry the tag; viewable is whether the tag is shown in the Backstop UI."
        )
    )


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_activity_tags(
    search: Annotated[
        str | None,
        Field(
            description=(
                "Optional case-insensitive substring of the tag name. Filters the cached "
                "catalog in memory — the catalog walk never sends `filter[name][like]`."
            ),
        ),
    ] = None,
    refresh: Annotated[
        bool,
        Field(description="Do not pass true unless the user reports a missing field."),
    ] = False,
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    activity_tags: ActivityTagsService = Depends(get_activity_tags_service),
) -> ListActivityTagsResponse:
    """List the standard Backstop activity-tag catalog.

    Use when you need tag ids, names, how many activities currently carry each tag, and whether
    a tag is shown in the Backstop UI. Instance tag names come back as data. Pass `search` to
    keep tags whose name contains that substring. Pass refresh=true only when the user reports
    a missing field.
    """
    catalog, cache = await activity_tags.get(client, refresh=refresh)
    tags = [ActivityTagResponse.from_tag(tag) for tag in catalog.values()]
    if search is not None:
        needle = search.casefold()
        tags = [tag for tag in tags if needle in tag.name.casefold()]
    return ListActivityTagsResponse(cache=cache, tags=tags)
