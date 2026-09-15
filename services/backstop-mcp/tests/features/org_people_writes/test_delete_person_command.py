"""`DeletePartyWithLocationsCommand` against `/people/{id}`."""

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

_ID = "27871657"
_NAME = "Jane Doe"
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


def _person_document(*, location_ids: tuple[str, ...] = (_LOC_1, _LOC_2)) -> dict[str, object]:
    return {
        "data": {
            "id": _ID,
            "type": "people",
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
                "attributes": {"locationTitle": f"Office {loc_id}"},
            }
            for loc_id in location_ids
        ],
    }


def _party_not_found() -> httpx.Response:
    return httpx.Response(
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


class TestDeletePartyWithLocationsAgainstPeople:
    @respx.mock
    async def test_delete_person_deletes_locations_before_the_party(
        self, client: BackstopClient
    ) -> None:
        preview = respx.get(f"{BASE_URL}/people/{_ID}").mock(
            return_value=httpx.Response(200, json=_person_document())
        )
        loc_1 = respx.delete(f"{BASE_URL}/contact-locations/{_LOC_1}").mock(
            return_value=httpx.Response(204)
        )
        loc_2 = respx.delete(f"{BASE_URL}/contact-locations/{_LOC_2}").mock(
            return_value=httpx.Response(204)
        )
        party = respx.delete(f"{BASE_URL}/people/{_ID}").mock(return_value=httpx.Response(204))

        result = await make_command(client).run(collection="people", party_id=_ID)

        assert result == (_LOC_1, _LOC_2)
        assert preview.call_count == 1
        assert loc_1.call_count == 1
        assert loc_2.call_count == 1
        assert party.call_count == 1
        include = recorded_params(preview)[0]["include"]
        assert include == "contactLocations"
        assert include != "locations"
        paths = [(request.method, request.url.path) for request in recorded_requests(respx.calls)]
        assert paths == [
            ("GET", f"/people/{_ID}"),
            ("DELETE", f"/contact-locations/{_LOC_1}"),
            ("DELETE", f"/contact-locations/{_LOC_2}"),
            ("DELETE", f"/people/{_ID}"),
        ]

    @respx.mock
    async def test_failed_location_delete_aborts_before_deleting_the_party(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/people/{_ID}").mock(
            return_value=httpx.Response(200, json=_person_document())
        )
        respx.delete(f"{BASE_URL}/contact-locations/{_LOC_1}").mock(
            return_value=httpx.Response(204)
        )
        respx.delete(f"{BASE_URL}/contact-locations/{_LOC_2}").mock(return_value=_party_not_found())
        party = respx.delete(f"{BASE_URL}/people/{_ID}").mock(return_value=httpx.Response(204))

        with pytest.raises(ToolError, match="was not deleted") as raised:
            await make_command(client).run(collection="people", party_id=_ID)

        message = str(raised.value)
        assert _LOC_2 in message
        assert "parent party" in message
        assert "999" not in message
        assert party.call_count == 0

    @respx.mock
    async def test_delete_sends_no_body_and_no_schema(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_ID}").mock(
            return_value=httpx.Response(200, json=_person_document(location_ids=(_LOC_1,)))
        )
        respx.delete(f"{BASE_URL}/contact-locations/{_LOC_1}").mock(
            return_value=httpx.Response(204, content=b"")
        )
        route = respx.delete(f"{BASE_URL}/people/{_ID}").mock(
            return_value=httpx.Response(204, content=b"")
        )
        spy = AsyncMock(wraps=client.delete)

        with patch.object(client, "delete", spy):
            await make_command(client).run(collection="people", party_id=_ID)

        request = recorded_requests(route.calls)[0]
        assert request.method == "DELETE"
        assert request.content in (b"", b"null")
        party_calls = [c for c in spy.await_args_list if c.args == (f"/people/{_ID}",)]
        assert len(party_calls) == 1
        assert party_calls[0].kwargs == {}

    @respx.mock
    async def test_zero_locations_deletes_the_party_only(self, client: BackstopClient) -> None:
        preview = respx.get(f"{BASE_URL}/people/{_ID}").mock(
            return_value=httpx.Response(200, json=_person_document(location_ids=()))
        )
        locations = respx.delete(url__regex=r".*/contact-locations/.*")
        party = respx.delete(f"{BASE_URL}/people/{_ID}").mock(return_value=httpx.Response(204))

        result = await make_command(client).run(collection="people", party_id=_ID)

        assert result == ()
        assert preview.call_count == 1
        assert recorded_params(preview)[0]["include"] == "contactLocations"
        assert locations.call_count == 0
        assert party.call_count == 1
        paths = [(request.method, request.url.path) for request in recorded_requests(respx.calls)]
        assert paths == [("GET", f"/people/{_ID}"), ("DELETE", f"/people/{_ID}")]

    @respx.mock
    async def test_include_locations_is_not_used(self, client: BackstopClient) -> None:
        preview = respx.get(f"{BASE_URL}/people/{_ID}").mock(
            return_value=httpx.Response(200, json=_person_document(location_ids=()))
        )
        respx.delete(f"{BASE_URL}/people/{_ID}").mock(return_value=httpx.Response(204))

        await make_command(client).run(collection="people", party_id=_ID)

        include = recorded_params(preview)[0]["include"]
        assert include == "contactLocations"
        assert include != "locations"
        for request in recorded_requests(respx.calls):
            assert request.url.params.get("include", "") != "locations"
