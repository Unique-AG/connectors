from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.articles import InvestorArticlesResponse
from with_intelligence_mcp.features.articles.dependencies import get_articles_query_factory
from with_intelligence_mcp.features.articles.queries import GetArticlesQuery
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

type GetArticlesResult = (
    InvestorArticlesResponse
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
    output_schema=published_output_schema(GetArticlesResult),
)
async def get_articles(
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
    limit: Annotated[int, Field(ge=1, le=50, description="How many articles to return.")] = 10,
    posted_since: Annotated[
        str | None,
        Field(description="ISO date. Only articles published on or after that date."),
    ] = None,
    resolve_investor_record_query: ResolveInvestorRecordQuery = Depends(
        get_resolve_investor_record_query_factory
    ),
    get_articles_query: GetArticlesQuery = Depends(get_articles_query_factory),
) -> GetArticlesResult:
    """Articles With Intelligence has tagged to one institutional investor: title, date, excerpt,
    body, and which firm each piece is about.

    Read `published_at` on each article. The page order is With Intelligence's, not a promise
    of newest-first. Use `body` for the article text. A snippet may have only an excerpt. Do
    not invent text that was not returned.
    """
    investor = await resolve_investor_record_query.run(name=name, investor_id=investor_id)
    if not isinstance(investor, InvestorExtendedAttributes):
        return investor
    try:
        return await get_articles_query.run(
            investor=investor,
            page=page,
            limit=limit,
            posted_since=posted_since,
        )
    except NotEntitled as error:
        return InvestorNotEntitledResponse(
            searched_for=name or str(investor.id),
            hint=f"With Intelligence refused {error.path} for this account.",
        )
