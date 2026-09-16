from pydantic import TypeAdapter

from with_intelligence_mcp.features.persons.fetch_people_for_organisation import PERSONS_PATH
from with_intelligence_mcp.features.persons.wi_responses import PersonExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import (
    NotFound,
    WithIntelligenceClient,
)

_PERSON_RESPONSE = TypeAdapter(PersonExtendedAttributes)


async def fetch_person(
    client: WithIntelligenceClient, person_id: int
) -> PersonExtendedAttributes | None:
    """`GET /v3/persons/{id}` — the listing carries only a name, so titles need this."""
    try:
        return await client.get_json(f"{PERSONS_PATH}/{person_id}", _PERSON_RESPONSE)
    except NotFound:
        return None
