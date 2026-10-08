import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.entity_types import SearchType
from tests.features.party_resolver.helpers import BASE_URL, make_get_party_name_query, resource


class TestGetPartyNameQuery:
    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(
        ("search_type", "fields"),
        [
            # Backstop 400s `/organizations` and `/contacts` on firstName/lastName.
            ("organizations", "name"),
            ("contacts", "name"),
            ("people", "name,firstName,lastName"),
            ("employees", "name,firstName,lastName"),
        ],
    )
    async def test_requests_only_fields_the_type_supports(
        self, client: BackstopClient, search_type: SearchType, fields: str
    ) -> None:
        route = respx.get(f"{BASE_URL}/{search_type}/42").mock(
            return_value=httpx.Response(
                200, json={"data": resource("42", search_type, name="Northwind")}
            )
        )

        name = await make_get_party_name_query(client).run(search_type=search_type, party_id="42")

        assert name == "Northwind"
        assert route.calls.last.request.url.params["fields"] == fields
