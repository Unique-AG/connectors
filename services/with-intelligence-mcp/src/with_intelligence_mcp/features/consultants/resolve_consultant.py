from with_intelligence_mcp.features.consultants.api_responses import ConsultantExtendedAttributes
from with_intelligence_mcp.features.consultants.fetch_consultant import fetch_consultant
from with_intelligence_mcp.features.consultants.responses import (
    ConsultantAmbiguousResponse,
    ConsultantCandidateResponse,
    ConsultantNotEntitledResponse,
    ConsultantNotFoundResponse,
)
from with_intelligence_mcp.features.consultants.search_consultants_by_name import (
    search_consultants_by_name,
)
from with_intelligence_mcp.with_intelligence_client import NotEntitled, WithIntelligenceClient

type ConsultantRecordResolution = (
    ConsultantExtendedAttributes
    | ConsultantAmbiguousResponse
    | ConsultantNotEntitledResponse
    | ConsultantNotFoundResponse
)


async def resolve_consultant(
    client: WithIntelligenceClient,
    name: str | None,
    consultant_id: int | None,
) -> ConsultantRecordResolution:
    if consultant_id is None:
        if name is None:
            return ConsultantNotFoundResponse(
                searched_for="", hint="Pass either name or consultant_id."
            )
        try:
            matches, total = await search_consultants_by_name(client, name)
        except NotEntitled as error:
            return ConsultantNotEntitledResponse(
                searched_for=name,
                hint=(
                    "With Intelligence refused the consultant search for this account "
                    f"({error.path}) — the data is outside its licensed packages."
                ),
            )
        if not matches:
            return ConsultantNotFoundResponse(
                searched_for=name,
                hint=(
                    "No consultant name contains that text. Matching is partial, so a shorter "
                    "or differently spelled fragment may find it."
                ),
            )
        if len(matches) > 1:
            return ConsultantAmbiguousResponse(
                searched_for=name,
                candidates=[
                    ConsultantCandidateResponse(
                        id=match.id, name=match.name, updated_at=match.updated_at
                    )
                    for match in matches
                ],
                total_matches=total,
            )
        consultant_id = matches[0].id

    try:
        record = await fetch_consultant(client, consultant_id)
    except NotEntitled as error:
        return ConsultantNotEntitledResponse(
            searched_for=name or str(consultant_id),
            hint=(
                f"With Intelligence refused {error.path} for this account — "
                "the data is outside its licensed packages."
            ),
        )
    if record is None:
        return ConsultantNotFoundResponse(
            searched_for=name or str(consultant_id),
            hint=f"No consultant with id {consultant_id}.",
        )
    return record
