import asyncio

from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.features.persons.fetch_people_for_organisation import (
    fetch_people_for_organisation,
)
from with_intelligence_mcp.features.persons.fetch_person import fetch_person
from with_intelligence_mcp.features.persons.project_person import project_person
from with_intelligence_mcp.features.persons.responses import (
    PeopleForInvestorResponse,
    PersonResponse,
)
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient


class GetPeopleForInvestorQuery:
    def __init__(self, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(
        self, *, investor: InvestorExtendedAttributes, limit: int
    ) -> PeopleForInvestorResponse:
        listed, total = await fetch_people_for_organisation(self._client, investor.id, limit=limit)
        details = await asyncio.gather(
            *(fetch_person(self._client, person.id) for person in listed)
        )
        people = [
            project_person(detail, investor.id)
            if detail
            else PersonResponse(id=listed[index].id, name=listed[index].name)
            for index, detail in enumerate(details)
        ]
        return PeopleForInvestorResponse(
            investor_id=investor.id,
            investor_name=investor.name,
            people=people,
            total_at_organisation=total,
            contacts_on_investor_record=investor.contacts_total,
            returned=len(people),
        )
