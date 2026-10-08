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
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def list_activity_tags(
    search: Annotated[
        str | None,
        Field(
            description=(
                "Optional case-insensitive substring of the tag name. Omit to list the "
                "whole catalog."
            ),
        ),
    ] = None,
    refresh: Annotated[
        bool,
        Field(description="Do not pass true unless the user reports a missing tag."),
    ] = False,
    activity_tags: ActivityTagsService = Depends(get_activity_tags_service),
) -> ListActivityTagsResponse:
    """List the standard Backstop activity-tag catalog.

    Search by the term and pass every matching id to search_activities `activity_tag_ids`.
    A term mentioned in activities is this search with that substring. Use when you
    need tag ids, names, how many activities currently carry each tag, and whether a tag is
    shown in the Backstop UI.
    Instance tag names come back as data. Pass `search` to keep tags whose name contains
    that substring. Pass refresh=true only when the user reports a missing tag.

    Call like: {"search": "follow"}
    """
    catalog, cache = await activity_tags.get(refresh=refresh)
    tags = [ActivityTagResponse.from_tag(tag) for tag in catalog.values()]
    if search is not None:
        needle = search.casefold()
        tags = [tag for tag in tags if needle in tag.name.casefold()]
    return ListActivityTagsResponse(cache=cache, tags=tags)
