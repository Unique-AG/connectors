"""`DeletePartyWithLocationsCommand` against `/organizations/{id}`."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    DeletePartyWithLocationsCommand,
    get_delete_party_with_locations_command_factory,
    get_modify_contact_location_command_factory,
)
from tests.helpers import BASE_URL, client_factory, credential, recorded_params, recorded_requests

_ID = "org-1"
_NAME = "Acme Advisors"
_LOC_1 = "loc-1"
_LOC_2 = "loc-2"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> DeletePartyWithLocationsCommand:
    return get_delete_party_with_locations_command_factory(
        client,
        modify_contact_location_command=get_modify_contact_location_command_factory(client),
    )


def _organization_document(
    *, location_ids: tuple[str, ...] = (_LOC_1, _LOC_2)
) -> dict[str, object]:
    return {
        "data": {
            "id": _ID,
            "type": "organizations",
            "attributes": {"name": _NAME},
            "relationships": {
                "contactLocations": {
                    "data": [{"type": "contact-locations", "id": loc_id} for loc_id in location_ids]
                }
            },
        },
        "included": [
            {
                "type": "contact-locations",
                "id": loc_id,
                "attributes": {"locationTitle": f"HQ {loc_id}"},
            }
            for loc_id in location_ids
        ],
    }


class TestDeletePartyWithLocationsAgainstOrganizations:
    @respx.mock
    async def test_deletes_locations_before_the_party(self, client: BackstopClient) -> None:
        preview = respx.get(f"{BASE_URL}/organizations/{_ID}").mock(
            return_value=httpx.Response(200, json=_organization_document())
        )
        respx.delete(f"{BASE_URL}/contact-locations/{_LOC_1}").mock(
            return_value=httpx.Response(204)
        )
        respx.delete(f"{BASE_URL}/contact-locations/{_LOC_2}").mock(
            return_value=httpx.Response(204)
        )
        party = respx.delete(f"{BASE_URL}/organizations/{_ID}").mock(
            return_value=httpx.Response(204)
        )

        result = await make_command(client).run(collection="organizations", party_id=_ID)

        assert result == (_LOC_1, _LOC_2)
        assert recorded_params(preview)[0]["include"] == "contactLocations"
        assert party.call_count == 1
        paths = [(request.method, request.url.path) for request in recorded_requests(respx.calls)]
        assert paths == [
            ("GET", f"/organizations/{_ID}"),
            ("DELETE", f"/contact-locations/{_LOC_1}"),
            ("DELETE", f"/contact-locations/{_LOC_2}"),
            ("DELETE", f"/organizations/{_ID}"),
        ]

    @respx.mock
    async def test_failed_location_delete_aborts_before_deleting_the_party(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/organizations/{_ID}").mock(
            return_value=httpx.Response(200, json=_organization_document())
        )
        respx.delete(f"{BASE_URL}/contact-locations/{_LOC_1}").mock(
            return_value=httpx.Response(204)
        )
        respx.delete(f"{BASE_URL}/contact-locations/{_LOC_2}").mock(
            return_value=httpx.Response(
                404,
                json={
                    "errors": [
                        {
                            "status": "404",
                            "code": "PartyNotFoundException",
                            "detail": "Party with id 999 was not found.",
                        }
                    ]
                },
            )
        )
        party = respx.delete(f"{BASE_URL}/organizations/{_ID}").mock(
            return_value=httpx.Response(204)
        )

        with pytest.raises(ToolError, match="was not deleted") as raised:
            await make_command(client).run(collection="organizations", party_id=_ID)

        assert _LOC_2 in str(raised.value)
        assert "parent party" in str(raised.value)
        assert party.call_count == 0

    @respx.mock
    async def test_delete_sends_no_body_and_no_schema(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/{_ID}").mock(
            return_value=httpx.Response(200, json=_organization_document(location_ids=()))
        )
        route = respx.delete(f"{BASE_URL}/organizations/{_ID}").mock(
            return_value=httpx.Response(204, content=b"")
        )
        spy = AsyncMock(wraps=client.delete)

        with patch.object(client, "delete", spy):
            await make_command(client).run(collection="organizations", party_id=_ID)

        request = recorded_requests(route.calls)[0]
        assert request.method == "DELETE"
        assert request.content in (b"", b"null")
        spy.assert_awaited_once_with(f"/organizations/{_ID}")

    @respx.mock
    async def test_zero_locations_deletes_the_party_only(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/{_ID}").mock(
            return_value=httpx.Response(200, json=_organization_document(location_ids=()))
        )
        locations = respx.delete(url__regex=r".*/contact-locations/.*")
        party = respx.delete(f"{BASE_URL}/organizations/{_ID}").mock(
            return_value=httpx.Response(204)
        )

        result = await make_command(client).run(collection="organizations", party_id=_ID)

        assert result == ()
        assert locations.call_count == 0
        assert party.call_count == 1

    @respx.mock
    async def test_include_locations_is_not_used(self, client: BackstopClient) -> None:
        preview = respx.get(f"{BASE_URL}/organizations/{_ID}").mock(
            return_value=httpx.Response(200, json=_organization_document(location_ids=()))
        )
        respx.delete(f"{BASE_URL}/organizations/{_ID}").mock(return_value=httpx.Response(204))

        await make_command(client).run(collection="organizations", party_id=_ID)

        assert recorded_params(preview)[0]["include"] == "contactLocations"
        for request in recorded_requests(respx.calls):
            assert request.url.params.get("include", "") != "locations"
