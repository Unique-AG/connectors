from pydantic import TypeAdapter

from with_intelligence_mcp.features.consultants.api_responses import ConsultantExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import NotFound, WithIntelligenceClient

_CONSULTANT_RESPONSE = TypeAdapter(ConsultantExtendedAttributes)


async def fetch_consultant(
    client: WithIntelligenceClient, consultant_id: int
) -> ConsultantExtendedAttributes | None:
    """`GET /v3/consultants/{id}`. `None` when the id does not exist."""
    try:
        return await client.get_json(f"/v3/consultants/{consultant_id}", _CONSULTANT_RESPONSE)
    except NotFound:
        return None
