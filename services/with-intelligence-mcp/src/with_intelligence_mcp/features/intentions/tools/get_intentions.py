from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.intentions import InvestorIntentionsResponse
from with_intelligence_mcp.features.intentions.dependencies import get_intentions_query_factory
from with_intelligence_mcp.features.intentions.queries import GetIntentionsQuery
from with_intelligence_mcp.features.investors import (
    InvestorAmbiguousResponse,
    InvestorExtendedAttributes,
    InvestorNotEntitledResponse,
    InvestorNotFoundResponse,
)
from with_intelligence_mcp.features.investors.dependencies import (
    get_resolve_investor_record_query_factory,
)
from with_intelligence_mcp.features.investors.queries import ResolveInvestorRecordQuery
from with_intelligence_mcp.models import published_output_schema
from with_intelligence_mcp.with_intelligence_client import NotEntitled

type GetIntentionsResult = (
    InvestorIntentionsResponse
    | InvestorAmbiguousResponse
    | InvestorNotEntitledResponse
    | InvestorNotFoundResponse
)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(GetIntentionsResult),
)
async def get_intentions(
    name: Annotated[
        str | None,
        Field(
            description=(
                "Investor name. Matching is partial, so a short name returns candidates to "
                "choose between. Omit when passing investor_id."
            )
        ),
    ] = None,
    investor_id: Annotated[int | None, Field(description="Investor id, when known.")] = None,
    page: Annotated[int, Field(ge=1, description="Page number to return.")] = 1,
    limit: Annotated[
        int,
        Field(
            ge=1, le=50, description="How many intentions to return, most recently updated first."
        ),
    ] = 25,
    updated_since: Annotated[
        str | None,
        Field(description="ISO date. Only intentions With Intelligence changed since then."),
    ] = None,
    resolve_investor_record_query: ResolveInvestorRecordQuery = Depends(
        get_resolve_investor_record_query_factory
    ),
    get_intentions_query: GetIntentionsQuery = Depends(get_intentions_query_factory),
) -> GetIntentionsResult:
    """An investor's forward-looking allocation intentions: asset class, strategy, ticket size,
    and whether each row is a stated preference or a live search.

    Amounts are US dollars, not the millions used for AUM. `not_entitled` means this subscription
    lacks the Intentions & Preferences add-on — do not describe that as the investor having no
    intentions. An empty list is a real empty result from an account that is licensed.
    """
    investor = await resolve_investor_record_query.run(name=name, investor_id=investor_id)
    if not isinstance(investor, InvestorExtendedAttributes):
        return investor
    try:
        return await get_intentions_query.run(
            investor=investor,
            page=page,
            limit=limit,
            updated_since=updated_since,
        )
    except NotEntitled as error:
        return InvestorNotEntitledResponse(
            searched_for=name or str(investor.id),
            hint=(
                f"With Intelligence refused {error.path} for this account. Intentions are a "
                "subscription add-on, so this means the account is not licensed for them."
            ),
        )
