"""`update_opportunity`: registered and wired through the command factory."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.opportunity_writes import (
    UpdatedOpportunityResponse,
    UpdateOpportunityCommand,
    UpdateOpportunityInput,
    get_update_opportunity_command_factory,
)
from backstop_mcp.features.opportunity_writes.tools.update_opportunity import update_opportunity
from backstop_mcp.server.tools import TOOLS
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    opportunity_stages_service,
    recorded_json_bodies,
    resource,
    system_users_service,
)
from tests.server.tools.helpers import object_dict, tool_model

_OPPORTUNITY: TypeAdapter[UpdateOpportunityInput] = TypeAdapter(UpdateOpportunityInput)
_ID = "5755101"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> UpdateOpportunityCommand:
    return get_update_opportunity_command_factory(
        client,
        opportunity_stages_service=opportunity_stages_service(client),
        system_users_service=system_users_service(client),
    )


def _document(description: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": {
                "id": _ID,
                "type": "opportunities",
                "attributes": {"description": description},
                "relationships": {},
            },
            "included": [],
        },
    )


class TestUpdateOpportunity:
    def test_is_registered(self) -> None:
        assert update_opportunity in TOOLS

    @respx.mock
    async def test_patches_the_description(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/opportunity-stages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [resource("42478", "opportunity-stages", name="Prospect")],
                    "links": {"next": None},
                },
            )
        )
        respx.get(f"{BASE_URL}/system-users").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {"next": None}})
        )
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_document("was"))
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_document("Corrected")
        )

        result = tool_model(
            await update_opportunity(
                opportunity=_OPPORTUNITY.validate_python(
                    {"opportunity_id": _ID, "description": "Corrected"}
                ),
                update_opportunity_command=make_command(client),
            ),
            UpdatedOpportunityResponse,
        )

        assert result.id == _ID
        assert result.resource_type == "opportunities"
        assert route.call_count == 1
        attributes = object_dict(object_dict(recorded_json_bodies(route)[0]["data"])["attributes"])
        assert attributes == {"description": "Corrected"}
