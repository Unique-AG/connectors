"""`create_organization`: registered and wired through the command factory."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    CreatedOrganizationResponse,
    CreateOrganizationCommand,
    CreateOrganizationInput,
    get_create_organization_command_factory,
)
from backstop_mcp.features.org_people_writes.tools.create_organization import create_organization
from backstop_mcp.features.ui_links import BuildEntityLinkUtil
from backstop_mcp.server.tools import TOOLS
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    recorded_json_bodies,
    system_users_service,
)
from tests.server.tools.helpers import object_dict, tool_model

_ORG: TypeAdapter[CreateOrganizationInput] = TypeAdapter(CreateOrganizationInput)
_ID = "8001"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> CreateOrganizationCommand:
    return get_create_organization_command_factory(
        client,
        system_users_service=system_users_service(client),
        build_entity_link_util=BuildEntityLinkUtil(ui_base_url=None),
    )


def _document(*, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={"data": {"id": _ID, "type": "organizations", "attributes": {"name": "Acme"}}},
    )


class TestCreateOrganization:
    def test_is_registered(self) -> None:
        assert create_organization in TOOLS

    @respx.mock
    async def test_posts_the_name(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/{_ID}").mock(return_value=_document())
        route = respx.post(f"{BASE_URL}/organizations").mock(return_value=_document(status=201))

        result = tool_model(
            await create_organization(
                organization=_ORG.validate_python({"name": "Acme"}),
                create_organization_command=make_command(client),
            ),
            CreatedOrganizationResponse,
        )

        assert result.id == _ID
        assert result.resource_type == "organizations"
        assert result.name == "Acme"
        assert route.call_count == 1
        attributes = object_dict(object_dict(recorded_json_bodies(route)[0]["data"])["attributes"])
        assert attributes == {"name": "Acme"}
