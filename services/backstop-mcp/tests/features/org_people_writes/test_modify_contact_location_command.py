"""`ModifyContactLocationCommand`: create as `contacts`, collision, delete body."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from pydantic import TypeAdapter, ValidationError

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
    async def test_a_location_id_patches_instead_of_creating(self, client: BackstopClient) -> None:
        create = respx.post(f"{BASE_URL}/contact-locations")
        patch = respx.patch(f"{BASE_URL}/contact-locations/{_LOCATION_ID}").mock(
            return_value=_created_document(_LOCATION_ID)
        )

        location_id = await get_modify_contact_location_command_factory(client).run(
            party_id=_PARTY_ID,
            location=_LOCATION.validate_python(
                {"location_id": _LOCATION_ID, "address": "1 Main St"}
            ),
            delete_location_id=None,
        )

        assert location_id == _LOCATION_ID
        assert create.call_count == 0
        assert patch.call_count == 1
        data = object_dict(recorded_json_bodies(patch)[0]["data"])
        assert data["id"] == _LOCATION_ID
        assert object_dict(data["attributes"]) == {"address": "1 Main St"}
        assert "relationships" not in data

    @respx.mock
    async def test_a_renamed_location_reports_a_title_collision(
        self, client: BackstopClient
    ) -> None:
        respx.patch(f"{BASE_URL}/contact-locations/{_LOCATION_ID}").mock(
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
                location=_LOCATION.validate_python(
                    {"location_id": _LOCATION_ID, "location_title": "Office"}
                ),
                delete_location_id=None,
            )

    def test_an_over_length_location_title_is_rejected_by_the_input_model(self) -> None:
        with pytest.raises(ValidationError):
            _LOCATION.validate_python({"location_title": "x" * 31})

    @respx.mock
    async def test_party_not_found_on_a_create_does_not_say_deleted(
        self, client: BackstopClient
    ) -> None:
        respx.post(f"{BASE_URL}/contact-locations").mock(
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
                location=_LOCATION.validate_python({"location_title": "Office"}),
                delete_location_id=None,
            )

        assert "created" in str(raised.value)
        assert "deleted" not in str(raised.value)

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
