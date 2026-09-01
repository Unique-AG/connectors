from with_intelligence_mcp.features.persons.api_responses import PersonExtendedAttributes
from with_intelligence_mcp.features.persons.fetch_people_for_organisation import PERSONS_PATH
from with_intelligence_mcp.with_intelligence_client import (
    NotFound,
    WithIntelligenceClient,
    narrow_dict,
)


async def fetch_person(
    client: WithIntelligenceClient, person_id: int
) -> PersonExtendedAttributes | None:
    """`GET /v3/persons/{id}` — the listing carries only a name, so titles need this."""
    try:
        body = await client.get_json(f"{PERSONS_PATH}/{person_id}")
    except NotFound:
        return None
    return PersonExtendedAttributes.model_validate(narrow_dict(body))
