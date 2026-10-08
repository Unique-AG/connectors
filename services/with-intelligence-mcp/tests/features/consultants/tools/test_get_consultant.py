"""`get_consultant`: contact details live on the address."""

import httpx
import respx

from tests.helpers import BASE_URL, build_client
from with_intelligence_mcp.features.consultants import ConsultantProfileResponse
from with_intelligence_mcp.features.consultants.queries import GetConsultantQuery
from with_intelligence_mcp.features.consultants.tools.get_consultant import (
    GetConsultantResult,
)
from with_intelligence_mcp.features.consultants.tools.get_consultant import (
    get_consultant as call_get_consultant,
)
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient

CONSULTANT: dict[str, object] = {
    "id": -1098972655,
    "name": "Example Associates",
    "website": "https://example.invalid",
    "address": {
        "city": "Boston",
        "email": "contact@example.invalid",
        "phone": "+1 617 555 0100",
        "state": {"id": 28, "name": "Massachusetts", "abbreviation": "MA"},
        "country": {"id": 840, "name": "United States"},
    },
    "services": [{"id": 4, "name": "Consultant"}, {"id": 24, "name": "Investment Consultant"}],
    "funds_primary_strategies": [{"id": 1, "name": "Global Macro"}],
}


async def get_consultant(
    *,
    client: WithIntelligenceClient,
    consultant_id: int | None = None,
) -> GetConsultantResult:
    return await call_get_consultant(
        consultant_id=consultant_id,
        get_consultant_query=GetConsultantQuery(client=client),
    )


class TestProjection:
    @respx.mock
    async def test_projects_contact_details_and_coverage(self) -> None:
        respx.get(f"{BASE_URL}/v3/consultants/-1098972655").mock(
            return_value=httpx.Response(200, json=CONSULTANT)
        )
        client, _ = build_client()
        result = await get_consultant(consultant_id=-1098972655, client=client)
        assert isinstance(result, ConsultantProfileResponse)
        assert result.location == "Boston, MA, United States"
        assert result.email == "contact@example.invalid"
        assert result.services == ["Consultant", "Investment Consultant"]
        assert result.strategies == ["Global Macro"]
