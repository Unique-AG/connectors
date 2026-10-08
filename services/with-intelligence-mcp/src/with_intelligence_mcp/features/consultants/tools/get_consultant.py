from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.consultants.dependencies import get_consultant_query_factory
from with_intelligence_mcp.features.consultants.queries import GetConsultantQuery
from with_intelligence_mcp.features.consultants.responses import (
    ConsultantAmbiguousResponse,
    ConsultantNotEntitledResponse,
    ConsultantNotFoundResponse,
    ConsultantProfileResponse,
)
from with_intelligence_mcp.models import published_output_schema

type GetConsultantResult = (
    ConsultantProfileResponse
    | ConsultantAmbiguousResponse
    | ConsultantNotEntitledResponse
    | ConsultantNotFoundResponse
)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(GetConsultantResult),
)
async def get_consultant(
    name: Annotated[
        str | None,
        Field(
            description=(
                "Consultant firm name. Matching is partial, so a short name returns candidates "
                "to choose between. Omit when passing consultant_id."
            )
        ),
    ] = None,
    consultant_id: Annotated[
        int | None,
        Field(description="With Intelligence consultant id, when it is already known."),
    ] = None,
    get_consultant_query: GetConsultantQuery = Depends(get_consultant_query_factory),
) -> GetConsultantResult:
    """Profile one consulting firm: location, contact details, the services it offers, and the
    strategies and asset classes it advises on.

    Pass a name and it is resolved first; several matches come back as candidates to choose
    between. `strategies` is what the firm covers, not a list of funds it manages.
    """
    return await get_consultant_query.run(name=name, consultant_id=consultant_id)
