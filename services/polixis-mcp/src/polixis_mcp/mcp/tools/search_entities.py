from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations
from pydantic import Field

from polixis_mcp import contexts
from polixis_mcp.mcp.dependencies import get_upstream
from polixis_mcp.mcp.inputs.cursor import Cursor
from polixis_mcp.mcp.inputs.cursor import page_query
from polixis_mcp.upstream import Upstream


@tool(
    title="Search Entities",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("entity_type", "countries", "page_size")
async def search_entities(
    *,
    name: Annotated[
        str | None,
        Field(
            min_length=1,
            description=(
                "A name, registration number, LEI or ISIN of an organization or person. "
                "Required unless `cursor` is given."
            ),
        ),
    ] = None,
    entity_type: Annotated[
        contexts.EntityType | None,
        Field(description="Only organizations or only people. Leave it out for both."),
    ] = None,
    countries: Annotated[
        list[str] | None,
        Field(
            description=(
                "ISO 3166-1 alpha-2 country codes, such as `ch`. A match needs only one of them."
            )
        ),
    ] = None,
    dates: Annotated[
        list[contexts.PartialDate] | None,
        Field(
            description=(
                "Dates such as a birth or registration date, as YYYY-MM-DD, YYYY-MM or YYYY. "
                "A match needs one of its dates within one of them. Polixis filters on it, so "
                "it narrows a common name better than comparing the matches yourself."
            )
        ),
    ] = None,
    page_size: Annotated[
        int,
        Field(
            ge=1,
            le=10,
            description="Matches per page, at most 10, which come to about 8,000 tokens. "
            "Polixis pages them itself.",
        ),
    ] = 10,
    cursor: Cursor = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.EntitySearchResults:
    """Find organizations and people in Polixis by name or identifier, with their sanctions and
    PEP flags, dates, countries and identifiers to tell matches apart.

    Call it first when you have a name or identifier: every other Polixis tool takes a match's
    `pid`. When the user gives a pid instead, call `resolve_permanent_id` with it. A match may
    not show that a person is a former PEP: before saying a person is not a PEP, read the
    `flags` of `get_entity_profiles`, which show FORMER_PEP. When `next_cursor` is set, more
    matches exist: pass it back as `cursor` to page through them.
    """
    query = page_query(
        contexts.EntitySearchQuery,
        cursor,
        name=name,
        entity_type=entity_type,
        countries=countries,
        dates=dates,
        page_size=page_size,
    )
    return await contexts.search_entities(upstream=upstream, query=query)
