"""`create_opportunity`: registered and wired through the command factory."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.opportunity_writes import (
    CreatedOpportunityResponse,
    CreateOpportunityCommand,
    CreateOpportunityInput,
    get_create_opportunity_command_factory,
)
from backstop_mcp.features.opportunity_writes.tools.create_opportunity import create_opportunity
from backstop_mcp.features.ui_links import BuildEntityLinkUtil
from backstop_mcp.server.tools import TOOLS
from tests.features.opportunity_writes.test_update_opportunity_command import VOCABULARY
from tests.features.party_resolver.helpers import ctx_never_elicit, make_resolve_party_query
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

_OPPORTUNITY: TypeAdapter[CreateOpportunityInput] = TypeAdapter(CreateOpportunityInput)
_ID = "9001"
_INVESTOR_ID = "c1"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_command(client: BackstopClient) -> CreateOpportunityCommand:
    return get_create_opportunity_command_factory(
        client,
        opportunity_stages_service=opportunity_stages_service(client),
        system_users_service=system_users_service(client),
        build_entity_link_util=BuildEntityLinkUtil(ui_base_url=None),
    )


def _stages_page() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                resource(
                    stage.id,
                    "opportunity-stages",
                    name=stage.name,
                    sortOrder=stage.sort_order,
                    closed=stage.closed,
                )
                for stage in VOCABULARY.values()
            ],
            "links": {"next": None},
        },
    )


def _document(*, status: int = 200, stage_id: str = "42478") -> httpx.Response:
    known = VOCABULARY[stage_id]
    return httpx.Response(
        status,
        json={
            "data": {
                "id": _ID,
                "type": "opportunities",
                "attributes": {"name": "Koch - CATS Select"},
                "relationships": {
                    "stage": {"data": {"id": stage_id, "type": "opportunity-stages"}}
                },
            },
            "included": [
                resource(
                    stage_id,
                    "opportunity-stages",
                    name=known.name,
                    sortOrder=known.sort_order,
                    closed=known.closed,
                )
            ],
        },
    )


class TestCreateOpportunity:
    def test_is_registered(self) -> None:
        assert create_opportunity in TOOLS

    @respx.mock
    async def test_creates_opportunity_for_trusted_investor_id(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/opportunity-stages").mock(return_value=_stages_page())
        route = respx.post(f"{BASE_URL}/opportunities").mock(return_value=_document(status=201))
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_document())

        result = tool_model(
            await create_opportunity(
                ctx_never_elicit(),
                opportunity=_OPPORTUNITY.validate_python(
                    {
                        "name": "Koch - CATS Select",
                        "currency_code": "USD",
                        "is_erisa": False,
                        "party_id": _INVESTOR_ID,
                    }
                ),
                resolve_party_query=make_resolve_party_query(client),
                create_opportunity_command=make_command(client),
            ),
            CreatedOpportunityResponse,
        )

        assert result.id == _ID
        assert result.resource_type == "opportunities"
        investor = object_dict(
            object_dict(recorded_json_bodies(route)[0]["data"])["relationships"]
        )["investor"]
        assert object_dict(object_dict(investor)["data"]) == {
            "type": "contacts",
            "id": _INVESTOR_ID,
        }
