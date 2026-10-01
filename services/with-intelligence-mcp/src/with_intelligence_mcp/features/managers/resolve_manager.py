from with_intelligence_mcp.features.managers.api_responses import ManagerExtendedAttributes
from with_intelligence_mcp.features.managers.fetch_manager import fetch_manager
from with_intelligence_mcp.features.managers.responses import (
    ManagerAmbiguousResponse,
    ManagerCandidateResponse,
    ManagerNotEntitledResponse,
    ManagerNotFoundResponse,
)
from with_intelligence_mcp.features.managers.search_managers_by_name import search_managers_by_name
from with_intelligence_mcp.with_intelligence_client import NotEntitled, WithIntelligenceClient

type ManagerRecordResolution = (
    ManagerExtendedAttributes
    | ManagerAmbiguousResponse
    | ManagerNotEntitledResponse
    | ManagerNotFoundResponse
)


async def resolve_manager(
    client: WithIntelligenceClient,
    name: str | None,
    manager_id: int | None,
) -> ManagerRecordResolution:
    if manager_id is None:
        if name is None:
            return ManagerNotFoundResponse(searched_for="", hint="Pass either name or manager_id.")
        try:
            matches, total = await search_managers_by_name(client, name)
        except NotEntitled as error:
            return ManagerNotEntitledResponse(
                searched_for=name,
                hint=(
                    "With Intelligence refused the manager search for this account "
                    f"({error.path}) — the data is outside its licensed packages."
                ),
            )
        if not matches:
            return ManagerNotFoundResponse(
                searched_for=name,
                hint=(
                    "No manager name contains that text. Matching is partial, so a shorter or "
                    "differently spelled fragment may find it."
                ),
            )
        if len(matches) > 1:
            return ManagerAmbiguousResponse(
                searched_for=name,
                candidates=[
                    ManagerCandidateResponse(
                        id=match.id, name=match.name, updated_at=match.updated_at
                    )
                    for match in matches
                ],
                total_matches=total,
            )
        manager_id = matches[0].id

    try:
        record = await fetch_manager(client, manager_id)
    except NotEntitled as error:
        return ManagerNotEntitledResponse(
            searched_for=name or str(manager_id),
            hint=(
                f"With Intelligence refused {error.path} for this account — "
                "the data is outside its licensed packages."
            ),
        )
    if record is None:
        return ManagerNotFoundResponse(
            searched_for=name or str(manager_id),
            hint=f"No manager with id {manager_id}.",
        )
    return record
