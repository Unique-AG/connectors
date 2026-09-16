from with_intelligence_mcp.features.investors.fetch_investor import fetch_investor
from with_intelligence_mcp.features.investors.resolve_investor import resolve_investor
from with_intelligence_mcp.features.investors.responses import (
    InvestorAmbiguousResponse,
    InvestorNotFoundResponse,
)
from with_intelligence_mcp.features.investors.wi_responses import InvestorExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import NotEntitled, WithIntelligenceClient

type InvestorRecordResolution = (
    InvestorExtendedAttributes | InvestorAmbiguousResponse | InvestorNotFoundResponse
)


async def resolve_investor_record(
    client: WithIntelligenceClient,
    name: str | None,
    investor_id: int | None,
) -> InvestorRecordResolution:
    if investor_id is None:
        if name is None:
            return InvestorNotFoundResponse(
                searched_for="", hint="Pass either name or investor_id."
            )
        resolved = await resolve_investor(client, name)
        if not isinstance(resolved, int):
            return resolved
        investor_id = resolved

    try:
        record = await fetch_investor(client, investor_id)
    except NotEntitled as error:
        return InvestorNotFoundResponse(
            searched_for=name or str(investor_id),
            hint=(
                f"With Intelligence refused {error.path} for this account — "
                "the data is outside its licensed packages."
            ),
        )

    if record is None:
        return InvestorNotFoundResponse(
            searched_for=name or str(investor_id),
            hint=f"No investor with id {investor_id}.",
        )
    return record
