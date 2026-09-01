from with_intelligence_mcp.features.investors.responses import (
    InvestorAmbiguousResponse,
    InvestorCandidateResponse,
    InvestorNotFoundResponse,
)
from with_intelligence_mcp.features.investors.search_investors_by_name import (
    search_investors_by_name,
)
from with_intelligence_mcp.with_intelligence_client import NotEntitled, WithIntelligenceClient


async def resolve_investor(
    client: WithIntelligenceClient, name: str, *, limit: int = 10
) -> int | InvestorAmbiguousResponse | InvestorNotFoundResponse:
    """A name to one investor id, or a list to choose between.

    Name matching is partial — "Virginia" matches 20 investors — so several matches are the
    normal case for a short name, and the total travels with the candidates because the list
    itself is capped.
    """
    try:
        matches, total = await search_investors_by_name(client, name, limit=limit)
    except NotEntitled as error:
        return InvestorNotFoundResponse(
            searched_for=name,
            hint=(
                "With Intelligence refused the investor search for this account "
                f"({error.path}) — the data is outside its licensed packages."
            ),
        )

    if not matches:
        return InvestorNotFoundResponse(
            searched_for=name,
            hint=(
                "No investor name contains that text. Matching is partial, so a shorter or "
                "differently spelled fragment may find it."
            ),
        )
    if len(matches) == 1:
        return matches[0].id
    return InvestorAmbiguousResponse(
        searched_for=name,
        candidates=[
            InvestorCandidateResponse(id=m.id, name=m.name, updated_at=m.updated_at)
            for m in matches
        ],
        total_matches=total,
    )
