"""`update_person`: registered and wired through the command factory."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    UpdatedPersonResponse,
    UpdatePersonCommand,
    UpdatePersonInput,
    get_modify_contact_location_command_factory,
    get_update_person_command_factory,
)
from backstop_mcp.features.org_people_writes.tools.update_person import update_person
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import ctx_never_elicit, make_resolve_party_query
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    recorded_json_bodies,
    system_users_service,
)
from tests.server.tools.helpers import object_dict, tool_model

_PERSON: TypeAdapter[UpdatePersonInput] = TypeAdapter(UpdatePersonInput)
_ID = "27871657"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> UpdatePersonCommand:
    return get_update_person_command_factory(
        client,
        system_users_service=system_users_service(client),
        modify_contact_location_command=get_modify_contact_location_command_factory(client),
    )


def _document() -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": {"id": _ID, "type": "people", "attributes": {"mobilePhone": "555-0100"}}},
    )


class TestUpdatePerson:
    def test_is_registered(self) -> None:
        assert update_person in TOOLS

    @respx.mock
    async def test_patches_the_job_title(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_document())
        route = respx.patch(f"{BASE_URL}/people/{_ID}").mock(return_value=_document())

        result = tool_model(
            await update_person(
                ctx_never_elicit(),
                person=_PERSON.validate_python(
                    {"party_id": _ID, "search_type": "people", "job_title": "Managing Director"}
                ),
                resolve_party_query=make_resolve_party_query(client),
                update_person_command=make_command(client),
            ),
            UpdatedPersonResponse,
        )

        assert result.id == _ID
        assert result.resource_type == "people"
        assert result.mobile_phone == "555-0100"
        assert route.call_count == 1
        attributes = object_dict(object_dict(recorded_json_bodies(route)[0]["data"])["attributes"])
        assert attributes == {"jobTitle": "Managing Director"}
