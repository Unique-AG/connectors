from pydantic import TypeAdapter

from with_intelligence_mcp.features.managers.api_responses import ManagerExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import NotFound, WithIntelligenceClient

_MANAGER_RESPONSE = TypeAdapter(ManagerExtendedAttributes)


async def fetch_manager(
    client: WithIntelligenceClient, manager_id: int
) -> ManagerExtendedAttributes | None:
    """`GET /v3/managers/{id}`. `None` when the id does not exist."""
    try:
        return await client.get_json(f"/v3/managers/{manager_id}", _MANAGER_RESPONSE)
    except NotFound:
        return None
