import asyncio
import logging

from pydantic import TypeAdapter

from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.features.persons.api_responses import (
    PersonExtendedAttributes,
    PersonListItemAttributes,
)
from with_intelligence_mcp.features.persons.responses import (
    PeopleForInvestorResponse,
    PersonResponse,
)
from with_intelligence_mcp.with_intelligence_client import (
    NotEntitled,
    NotFound,
    Page,
    QueryValue,
    WithIntelligenceClient,
)

logger = logging.getLogger(__name__)
_PERSON_RESPONSE = TypeAdapter(PersonExtendedAttributes)
_PEOPLE_PAGE = TypeAdapter(Page[PersonListItemAttributes])


class GetPeopleForInvestorQuery:
    def __init__(self, *, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(
        self, *, investor: InvestorExtendedAttributes, page: int, limit: int
    ) -> PeopleForInvestorResponse:
        listed, total = await _fetch_people_for_organisation(
            self._client, investor.id, page=page, limit=limit
        )
        details = await asyncio.gather(
            *(_fetch_person(self._client, person.id) for person in listed)
        )
        people = [
            PersonResponse.from_attributes(detail, organisation_id=investor.id)
            if detail
            else PersonResponse(id=listed[index].id, name=listed[index].name)
            for index, detail in enumerate(details)
        ]
        response = PeopleForInvestorResponse(
            investor_id=investor.id,
            investor_name=investor.name,
            people=people,
            total_at_organisation=total,
            contacts_on_investor_record=investor.contacts_total,
            returned=len(people),
            page=page,
            has_more=(page - 1) * limit + len(people) < total,
        )
        logger.info(
            "people.investor.fetched",
            extra={"investor_id": investor.id, "returned": response.returned, "total": total},
        )
        return response


async def _fetch_person(
    client: WithIntelligenceClient, person_id: int
) -> PersonExtendedAttributes | None:
    try:
        return await client.get_json(f"/v3/persons/{person_id}", _PERSON_RESPONSE)
    except NotEntitled, NotFound:
        return None


async def _fetch_people_for_organisation(
    client: WithIntelligenceClient,
    organisation_id: int,
    *,
    page: int,
    limit: int,
) -> tuple[list[PersonListItemAttributes], int]:
    params: dict[str, QueryValue] = {
        "organisation_id": [organisation_id],
        "sort[updated_at]": "desc",
    }
    if client.asset_class_groups:
        params["asset_class_group"] = list(client.asset_class_groups)

    response = await client.get_page(
        "/v3/persons", _PEOPLE_PAGE, params, page=page, page_size=limit
    )
    return response.results, response.pagination.total
