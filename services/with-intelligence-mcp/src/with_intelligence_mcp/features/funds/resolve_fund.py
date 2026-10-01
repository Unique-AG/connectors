from with_intelligence_mcp.features.funds.api_responses import FundExtendedAttributes
from with_intelligence_mcp.features.funds.fetch_fund import fetch_fund
from with_intelligence_mcp.features.funds.responses import (
    FundAmbiguousResponse,
    FundCandidateResponse,
    FundNotEntitledResponse,
    FundNotFoundResponse,
)
from with_intelligence_mcp.features.funds.search_funds_by_name import search_funds_by_name
from with_intelligence_mcp.with_intelligence_client import NotEntitled, WithIntelligenceClient

type FundRecordResolution = (
    FundExtendedAttributes | FundAmbiguousResponse | FundNotEntitledResponse | FundNotFoundResponse
)


async def resolve_fund(
    client: WithIntelligenceClient,
    name: str | None,
    fund_id: int | None,
) -> FundRecordResolution:
    if fund_id is None:
        if name is None:
            return FundNotFoundResponse(searched_for="", hint="Pass either name or fund_id.")
        try:
            matches, total = await search_funds_by_name(client, name)
        except NotEntitled as error:
            return FundNotEntitledResponse(
                searched_for=name,
                hint=(
                    "With Intelligence refused the fund search for this account "
                    f"({error.path}) — the data is outside its licensed packages."
                ),
            )
        if not matches:
            return FundNotFoundResponse(
                searched_for=name,
                hint=(
                    "No fund name contains that text. Matching is partial, so a shorter or "
                    "differently spelled fragment may find it."
                ),
            )
        if len(matches) > 1:
            return FundAmbiguousResponse(
                searched_for=name,
                candidates=[
                    FundCandidateResponse(id=match.id, name=match.name, updated_at=match.updated_at)
                    for match in matches
                ],
                total_matches=total,
            )
        fund_id = matches[0].id

    try:
        record = await fetch_fund(client, fund_id)
    except NotEntitled as error:
        return FundNotEntitledResponse(
            searched_for=name or str(fund_id),
            hint=(
                f"With Intelligence refused {error.path} for this account — "
                "the data is outside its licensed packages."
            ),
        )
    if record is None:
        return FundNotFoundResponse(
            searched_for=name or str(fund_id),
            hint=f"No fund with id {fund_id}.",
        )
    return record
