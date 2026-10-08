"""`get_manager`: provider lists and AUM in millions."""

import httpx
import respx

from tests.helpers import BASE_URL, build_client, page_body
from with_intelligence_mcp.features.managers import (
    ManagerNotFoundResponse,
    ManagerProfileResponse,
)
from with_intelligence_mcp.features.managers.queries import GetManagerQuery
from with_intelligence_mcp.features.managers.tools.get_manager import (
    GetManagerResult,
)
from with_intelligence_mcp.features.managers.tools.get_manager import (
    get_manager as call_get_manager,
)
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient

MANAGER: dict[str, object] = {
    "id": 10,
    "name": "Example Manager",
    "city": "Westport",
    "country": {"id": 840, "name": "United States"},
    "prime_broker": [{"id": 5, "name": "JP Morgan"}],
    "aums": [{"aum": 85000, "type_name": "GROUP", "is_estimate": False}],
    "sec_registered_firm": True,
}


async def get_manager(
    *,
    client: WithIntelligenceClient,
    name: str | None = None,
    manager_id: int | None = None,
) -> GetManagerResult:
    return await call_get_manager(
        name=name,
        manager_id=manager_id,
        get_manager_query=GetManagerQuery(client=client),
    )


class TestProjection:
    @respx.mock
    async def test_projects_location_providers_and_aum_in_millions(self) -> None:
        respx.get(f"{BASE_URL}/v3/managers/10").mock(return_value=httpx.Response(200, json=MANAGER))
        client, _ = build_client()
        result = await get_manager(manager_id=10, client=client)
        assert isinstance(result, ManagerProfileResponse)
        assert result.location == "Westport, United States"
        assert result.prime_brokers == ["JP Morgan"]
        assert result.aums is not None
        assert result.aums[0].value_millions == 85000
        assert result.sec_registered_firm is True


class TestResolution:
    @respx.mock
    async def test_an_unknown_name_is_not_found(self) -> None:
        respx.get(f"{BASE_URL}/v3/managers").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        client, _ = build_client()
        result = await get_manager(name="Nobody", client=client)
        assert isinstance(result, ManagerNotFoundResponse)
