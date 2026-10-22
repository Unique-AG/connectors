from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.upstream import Upstream


@tool(
    title="Get Reference Data",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def get_reference_data(
    kind: Annotated[
        contexts.ReferenceKind,
        Field(
            description=(
                "countries for WATCHLIST ISO alpha-3 codes. nationalities for passport ICAO "
                "codes. providers, search_filters, or api_info."
            )
        ),
    ],
    upstream: Upstream = Depends(get_upstream),
) -> contexts.ReferenceData:
    """Look up country codes, passport nationalities, providers, case-search filters, or API info.

    WATCHLIST nationality and residence use countries. Passport issuing state and nationality
    use nationalities.
    """
    return await contexts.get_reference_data(upstream=upstream, kind=kind)
