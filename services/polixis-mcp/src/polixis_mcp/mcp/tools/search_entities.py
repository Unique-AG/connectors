from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations
from pydantic import Field

from polixis_mcp import contexts
from polixis_mcp.mcp.dependencies import get_upstream
from polixis_mcp.upstream import Upstream


@tool(
    title="Search Entities",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("entity_type", "countries", "page", "page_size")
async def search_entities(
    *,
    name: Annotated[
        str,
        Field(
            min_length=1,
            description="A name, registration number, LEI or ISIN of an organization or person.",
        ),
    ],
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
    page: Annotated[int, Field(ge=1, description="The page to return, from 1.")] = 1,
    page_size: Annotated[int, Field(ge=1, le=50, description="Matches per page.")] = 10,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.EntitySearchResults:
    """Find organizations and people in Polixis by name or identifier, with their sanctions and
    PEP flags.

    Call it first: every other Polixis tool takes a match's `pid` as its `id`, such as
    `get_corporate_profile`, `get_ultimate_beneficial_owners` or `get_smart_graph`.
    """
    return await contexts.search_entities(
        upstream=upstream,
        name=name,
        entity_type=entity_type,
        countries=countries or [],
        page=page,
        page_size=page_size,
    )
