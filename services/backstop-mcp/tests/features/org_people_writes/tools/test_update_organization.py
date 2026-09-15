"""`update_organization`: registered and wired through the command factory."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people_writes import (
    UpdatedOrganizationResponse,
    UpdateOrganizationCommand,
    UpdateOrganizationInput,
    get_modify_contact_location_command_factory,
    get_update_organization_command_factory,
)
from backstop_mcp.features.org_people_writes.tools.update_organization import update_organization
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

_ORG: TypeAdapter[UpdateOrganizationInput] = TypeAdapter(UpdateOrganizationInput)
_ID = "1001"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> UpdateOrganizationCommand:
    return get_update_organization_command_factory(
        client,
        system_users_service=system_users_service(client),
        modify_contact_location_command=get_modify_contact_location_command_factory(client),
    )


def _document() -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": {"id": _ID, "type": "organizations", "attributes": {"name": "Acme"}}},
    )


class TestUpdateOrganization:
    def test_is_registered(self) -> None:
        assert update_organization in TOOLS

    @respx.mock
    async def test_patches_the_website(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/{_ID}").mock(return_value=_document())
        route = respx.patch(f"{BASE_URL}/organizations/{_ID}").mock(return_value=_document())

        result = tool_model(
            await update_organization(
                ctx_never_elicit(),
                organization=_ORG.validate_python(
                    {
                        "party_id": _ID,
                        "search_type": "organizations",
                        "website": "https://example.com",
                    }
                ),
                resolve_party_query=make_resolve_party_query(client),
                update_organization_command=make_command(client),
            ),
            UpdatedOrganizationResponse,
        )

        assert result.id == _ID
        assert result.resource_type == "organizations"
        assert route.call_count == 1
        attributes = object_dict(object_dict(recorded_json_bodies(route)[0]["data"])["attributes"])
        assert attributes == {"website": "https://example.com"}
