from with_intelligence_mcp.features.persons.api_responses import PersonListItemAttributes
from with_intelligence_mcp.with_intelligence_client import QueryValue, WithIntelligenceClient

PERSONS_PATH = "/v3/persons"


async def fetch_people_for_organisation(
    client: WithIntelligenceClient, organisation_id: int, *, limit: int
) -> tuple[list[PersonListItemAttributes], int]:
    """People the person search attributes to one organisation, plus how many it reports.

    Note the count disagrees with the investor record's own `contacts` list, which is longer.
    Which is authoritative is undocumented, so both travel to the caller.
    """
    params: dict[str, QueryValue] = {"organisation_id": [organisation_id]}
    if client.settings.asset_class_groups:
        params["asset_class_group"] = list(client.settings.asset_class_groups)

    page = await client.get_page(PERSONS_PATH, params, page=1, page_size=limit)
    people = [
        PersonListItemAttributes.model_validate(record) for record in page.results if "id" in record
    ]
    return people, page.pagination.total
