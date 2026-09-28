from pydantic import TypeAdapter

from with_intelligence_mcp.features.persons.api_responses import PersonExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import (
    NotEntitled,
    NotFound,
    WithIntelligenceClient,
)

_PERSON_RESPONSE = TypeAdapter(PersonExtendedAttributes)


async def fetch_person(
    client: WithIntelligenceClient, person_id: int
) -> PersonExtendedAttributes | None:
    """`GET /v3/persons/{id}` — the listing carries only a name, so titles need this."""
    try:
        return await client.get_json(f"/v3/persons/{person_id}", _PERSON_RESPONSE)
    except NotEntitled, NotFound:
        return None
