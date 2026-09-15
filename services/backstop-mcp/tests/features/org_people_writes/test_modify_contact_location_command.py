"""`ModifyContactLocationCommand`: create as `contacts`, collision, delete body."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    ContactLocationInput,
    get_modify_contact_location_command_factory,
)
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    recorded_json_bodies,
    recorded_requests,
)
from tests.server.tools.helpers import object_dict

_LOCATION: TypeAdapter[ContactLocationInput] = TypeAdapter(ContactLocationInput)
_PARTY_ID = "27871657"
_LOCATION_ID = "loc-9"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _created_document(location_id: str) -> httpx.Response:
    return httpx.Response(
        201,
        json={
            "data": {
                "id": location_id,
                "type": "contact-locations",
                "attributes": {"locationTitle": "Office"},
            }
        },
    )


class TestModifyContactLocationCommand:
    @respx.mock
    async def test_location_create_links_the_contact_as_type_contacts(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(f"{BASE_URL}/contact-locations").mock(
            return_value=_created_document("loc-1")
        )

        location_id = await get_modify_contact_location_command_factory(client).run(
            party_id=_PARTY_ID,
            location=_LOCATION.validate_python({"location_title": "Office", "city": "Chicago"}),
            delete_location_id=None,
        )

        assert location_id == "loc-1"
        body = recorded_json_bodies(route)[0]
        data = object_dict(body["data"])
        assert data["type"] == "contact-locations"
        assert "id" not in data
        attributes = object_dict(data["attributes"])
        assert attributes["locationTitle"] == "Office"
        assert attributes["city"] == "Chicago"
        for derived in (
            "cityResolvedName",
            "countryCode",
            "countryResolvedName",
            "stateResolvedName",
            "primaryLocation",
        ):
            assert derived not in attributes
        contact = object_dict(object_dict(object_dict(data["relationships"])["contact"])["data"])
        assert contact == {"type": "contacts", "id": _PARTY_ID}

    @respx.mock
    async def test_duplicate_location_title_is_reported_as_a_collision(
        self, client: BackstopClient
    ) -> None:
        respx.post(f"{BASE_URL}/contact-locations").mock(
            return_value=httpx.Response(
                400,
                json={
                    "errors": [
                        {
                            "status": "400",
                            "detail": "Location Names for a party must be unique.",
                        }
                    ]
                },
            )
        )

        with pytest.raises(ToolError, match="already used"):
            await get_modify_contact_location_command_factory(client).run(
                party_id=_PARTY_ID,
                location=_LOCATION.validate_python({"location_title": "Office"}),
                delete_location_id=None,
            )

    @respx.mock
    async def test_location_delete_sends_no_body_and_no_schema(
        self, client: BackstopClient
    ) -> None:
        route = respx.delete(f"{BASE_URL}/contact-locations/{_LOCATION_ID}").mock(
            return_value=httpx.Response(204, content=b"")
        )

        location_id = await get_modify_contact_location_command_factory(client).run(
            party_id=_PARTY_ID,
            location=None,
            delete_location_id=_LOCATION_ID,
        )

        assert location_id is None
        assert route.call_count == 1
        request = recorded_requests(route.calls)[0]
        assert request.content in (b"", b"null")
        assert request.method == "DELETE"

    @respx.mock
    async def test_party_not_found_on_location_delete_is_translated(
        self, client: BackstopClient
    ) -> None:
        respx.delete(f"{BASE_URL}/contact-locations/{_LOCATION_ID}").mock(
            return_value=httpx.Response(
                404,
                json={
                    "errors": [
                        {
                            "status": "404",
                            "code": "PartyNotFoundException",
                            "detail": f"Party with id {_PARTY_ID} was not found.",
                        }
                    ]
                },
            )
        )

        with pytest.raises(ToolError, match="parent party") as raised:
            await get_modify_contact_location_command_factory(client).run(
                party_id=_PARTY_ID,
                location=None,
                delete_location_id=_LOCATION_ID,
            )

        assert "location not found" not in str(raised.value).casefold()
        assert "missing location" in str(raised.value).casefold()
