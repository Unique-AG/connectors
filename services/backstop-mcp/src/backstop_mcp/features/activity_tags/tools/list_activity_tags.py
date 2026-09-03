from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.activity_tags import (
    ActivityTagResponse,
    ActivityTagsService,
    ListActivityTagsResponse,
    get_activity_tags_service,
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
    activity_tags: ActivityTagsService = Depends(get_activity_tags_service),
) -> ListActivityTagsResponse:
    """List the standard Backstop activity-tag catalog.

    Use when you need tag ids, names, how many activities currently carry each tag, and whether
    a tag is shown in the Backstop UI. Instance tag names come back as data. Pass `search` to
    keep tags whose name contains that substring. Pass refresh=true only when the user reports
    a missing field.
    """
    catalog, cache = await activity_tags.get(refresh=refresh)
    tags = [ActivityTagResponse.from_tag(tag) for tag in catalog.values()]
    if search is not None:
        needle = search.casefold()
        tags = [tag for tag in tags if needle in tag.name.casefold()]
    return ListActivityTagsResponse(cache=cache, tags=tags)
