from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.contact_sources import (
    ListContactSourcesQuery,
    ListContactSourcesResponse,
    get_list_contact_sources_query_factory,
)
from backstop_mcp.models import published_output_schema


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(ListContactSourcesResponse),
)
async def list_contact_sources(
    search: Annotated[
        str | None,
        Field(
            description=(
                "Optional case-insensitive substring of the source name. The argument is "
                "`search`. Filters the walk in memory — the query never sends "
                "`filter[name][like]` (`GET /contact-sources` rejects it)."
            ),
        ),
    ] = None,
    refresh: Annotated[
        bool,
        Field(description="Do not pass true unless the user reports a missing source."),
    ] = False,
    list_contact_sources_query: ListContactSourcesQuery = Depends(
        get_list_contact_sources_query_factory
    ),
) -> ListContactSourcesResponse:
    """List the standard Backstop contact-source vocabulary.

    Use when you need a `contact_source_id` for create_person, update_person,
    create_organization, or update_organization. These are first-class CRM values,
    not custom fields — do not look them up on list_custom_fields. Pass `search` to
    keep sources whose name contains that substring. Pass refresh=true only when
    the user reports a missing source.

    Call like: {"search": "intro"}
    """
    return await list_contact_sources_query.run(search=search, refresh=refresh)
