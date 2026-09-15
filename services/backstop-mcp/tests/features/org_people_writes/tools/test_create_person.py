"""`create_person`: registered and wired through the command factory."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    CreatedPersonResponse,
    CreatePersonCommand,
    CreatePersonInput,
    get_create_person_command_factory,
)
from backstop_mcp.features.org_people_writes.tools.create_person import create_person
from backstop_mcp.server.tools import TOOLS
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    recorded_json_bodies,
    system_users_service,
)
from tests.server.tools.helpers import object_dict, tool_model

_PERSON: TypeAdapter[CreatePersonInput] = TypeAdapter(CreatePersonInput)
_ID = "9001"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> CreatePersonCommand:
    return get_create_person_command_factory(
        client, system_users_service=system_users_service(client)
    )


def _document(*, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "data": {
                "id": _ID,
                "type": "people",
                "attributes": {"name": "Smith", "mobilePhone": "555-0100"},
            }
        },
    )


class TestCreatePerson:
    def test_is_registered(self) -> None:
        assert create_person in TOOLS

    @respx.mock
    async def test_posts_last_name_and_gender(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/people/{_ID}").mock(return_value=_document())
        route = respx.post(f"{BASE_URL}/people").mock(return_value=_document(status=201))

        result = tool_model(
            await create_person(
                person=_PERSON.validate_python({"last_name": "Smith", "gender": "Female"}),
                create_person_command=make_command(client),
            ),
            CreatedPersonResponse,
        )

        assert result.id == _ID
        assert result.resource_type == "people"
        assert result.name == "Smith"
        assert result.mobile_phone == "555-0100"
        assert route.call_count == 1
        attributes = object_dict(object_dict(recorded_json_bodies(route)[0]["data"])["attributes"])
        assert attributes == {"lastName": "Smith", "gender": "Female"}
