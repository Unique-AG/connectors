"""`CreateOpportunityCommand`: POST payload shape, stage resolve, re-read stage."""

from collections.abc import AsyncGenerator

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.opportunities import OpportunityStageResponse
from backstop_mcp.features.opportunity_writes import (
    CreatedOpportunityResponse,
    CreateOpportunityCommand,
    CreateOpportunityInput,
    get_create_opportunity_command_factory,
)
from backstop_mcp.features.opportunity_writes.commands._opportunity_attributes import (
    unique_catalog_entity_type_id,
)
from tests.features.opportunity_writes.test_update_opportunity_command import VOCABULARY
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    opportunity_stages_service,
    recorded_json_bodies,
    recorded_params,
    resource,
    system_users_service,
)
from tests.server.tools.helpers import object_dict

_OPPORTUNITY: TypeAdapter[CreateOpportunityInput] = TypeAdapter(CreateOpportunityInput)
_ID = "9001"
_INVESTOR_ID = "c1"
_REPRESENTATIVE_ID = "2967455"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _create(**payload: object) -> CreateOpportunityInput:
    return _OPPORTUNITY.validate_python(
        {
            "name": "Koch - CATS Select",
            "currency_code": "USD",
            "is_erisa": False,
            "party_id": _INVESTOR_ID,
            **payload,
        }
    )


def make_command(client: BackstopClient) -> CreateOpportunityCommand:
    return get_create_opportunity_command_factory(
        client,
        opportunity_stages_service=opportunity_stages_service(client),
        system_users_service=system_users_service(client),
    )


def _data(body: dict[str, object]) -> dict[str, object]:
    return object_dict(body["data"])


def _attributes(body: dict[str, object]) -> dict[str, object]:
    return object_dict(_data(body)["attributes"])


def _relationships(body: dict[str, object]) -> dict[str, object]:
    return object_dict(_data(body)["relationships"])


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


def _users_page() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                resource(_REPRESENTATIVE_ID, "system-users", name="Jane Doe", userName="jdoe"),
            ],
            "links": {"next": None},
        },
    )


def _opportunity_document(
    opportunity_id: str,
    *,
    status: int = 200,
    stage_id: str | None = "42478",
    attributes: dict[str, object] | None = None,
) -> httpx.Response:
    relationships: dict[str, object] = {}
    included: list[dict[str, object]] = []
    if stage_id is not None:
        known = VOCABULARY.get(stage_id)
        relationships["stage"] = {"data": {"id": stage_id, "type": "opportunity-stages"}}
        included.append(
            resource(
                stage_id,
                "opportunity-stages",
                name=known.name if known is not None else "Prospect",
                sortOrder=known.sort_order if known is not None else 1,
                closed=known.closed if known is not None else False,
            )
        )
    return httpx.Response(
        status,
        json={
            "data": {
                "id": opportunity_id,
                "type": "opportunities",
                "attributes": attributes or {},
                "relationships": relationships,
            },
            "included": included,
        },
    )


def _mock_write(*, stage_id: str | None = "42478", **attributes: object) -> respx.Route:
    payload = dict(attributes)
    respx.get(f"{BASE_URL}/opportunity-stages").mock(return_value=_stages_page())
    respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
        return_value=_opportunity_document(_ID, stage_id=stage_id, attributes=payload)
    )
    return respx.post(f"{BASE_URL}/opportunities").mock(
        return_value=_opportunity_document(_ID, status=201, stage_id=stage_id, attributes=payload)
    )


class TestCreateOpportunityCommand:
    @respx.mock
    async def test_create_opportunity_sends_investor_as_a_relationship(
        self, client: BackstopClient
    ) -> None:
        route = _mock_write(name="Koch - CATS Select")

        await make_command(client).run(opportunity=_create(), investor_id=_INVESTOR_ID)

        body = recorded_json_bodies(route)[0]
        investor = object_dict(_relationships(body)["investor"])
        assert object_dict(investor["data"]) == {"type": "contacts", "id": _INVESTOR_ID}
        assert "investor" not in _attributes(body)
        assert "resourceId" not in _attributes(body)
        assert "resourceType" not in _attributes(body)

    @respx.mock
    async def test_required_fields_are_on_the_wire(self, client: BackstopClient) -> None:
        route = _mock_write()

        await make_command(client).run(opportunity=_create(), investor_id=_INVESTOR_ID)

        assert _attributes(recorded_json_bodies(route)[0]) == {
            "name": "Koch - CATS Select",
            "currencyCode": "USD",
            "isErisa": False,
        }

    @respx.mock
    async def test_unsupplied_optional_fields_are_omitted(self, client: BackstopClient) -> None:
        route = _mock_write()

        await make_command(client).run(opportunity=_create(), investor_id=_INVESTOR_ID)

        body = recorded_json_bodies(route)[0]
        assert set(_attributes(body)) == {"name", "currencyCode", "isErisa"}
        assert set(_relationships(body)) == {"investor"}

    @respx.mock
    async def test_stage_name_is_resolved_to_a_catalog_id(self, client: BackstopClient) -> None:
        route = _mock_write(stage_id="42482")

        await make_command(client).run(opportunity=_create(stage="IDD"), investor_id=_INVESTOR_ID)

        stage = object_dict(_relationships(recorded_json_bodies(route)[0])["stage"])
        assert object_dict(stage["data"]) == {"type": "opportunity-stages", "id": "42482"}

    @respx.mock
    async def test_unknown_stage_does_not_post(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/opportunity-stages").mock(return_value=_stages_page())
        post = respx.post(f"{BASE_URL}/opportunities")

        with pytest.raises(ToolError, match="Available stages:.*IDD"):
            await make_command(client).run(
                opportunity=_create(stage="Not A Stage"), investor_id=_INVESTOR_ID
            )

        assert post.call_count == 0

    @respx.mock
    async def test_created_stage_comes_from_the_reread(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/opportunity-stages").mock(return_value=_stages_page())
        respx.post(f"{BASE_URL}/opportunities").mock(
            return_value=_opportunity_document(
                _ID, status=201, stage_id=None, attributes={"name": "Posted"}
            )
        )
        get_route = respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(
                _ID, stage_id="42482", attributes={"name": "Koch - CATS Select"}
            )
        )

        result = await make_command(client).run(
            opportunity=_create(stage="IDD"), investor_id=_INVESTOR_ID
        )

        assert recorded_params(get_route)[0]["include"] == "stage,clientDefinedEntityType"
        assert isinstance(result, CreatedOpportunityResponse)
        assert result.id == _ID
        assert result.resource_type == "opportunities"
        assert result.name == "Koch - CATS Select"
        assert result.stage == "IDD"
        assert result.stage_id == "42482"
        assert result.warnings == ()

    @respx.mock
    async def test_unknown_owner_login_does_not_post(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/system-users").mock(return_value=_users_page())
        post = respx.post(f"{BASE_URL}/opportunities")

        with pytest.raises(ToolError, match="No Backstop system user"):
            await make_command(client).run(
                opportunity=_create(owner_login="nobody"), investor_id=_INVESTOR_ID
            )

        assert post.call_count == 0

    @respx.mock
    async def test_owner_login_is_resolved_to_a_system_user_id(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/system-users").mock(return_value=_users_page())
        route = _mock_write()

        await make_command(client).run(
            opportunity=_create(owner_login="jdoe"), investor_id=_INVESTOR_ID
        )

        representative = object_dict(
            _relationships(recorded_json_bodies(route)[0])["representative"]
        )
        assert object_dict(representative["data"]) == {
            "type": "system-users",
            "id": _REPRESENTATIVE_ID,
        }


class TestUniqueCatalogEntityTypeId:
    def test_returns_the_only_type_id(self) -> None:
        catalog = {
            "a": OpportunityStageResponse(id="a", name="IDD", opportunity_type_ids=("16",)),
            "b": OpportunityStageResponse(id="b", name="Project", opportunity_type_ids=("16",)),
        }
        assert unique_catalog_entity_type_id(catalog) == "16"

    def test_returns_none_when_types_differ(self) -> None:
        catalog = {
            "a": OpportunityStageResponse(id="a", name="Prospect", opportunity_type_ids=("16",)),
            "b": OpportunityStageResponse(id="b", name="Other", opportunity_type_ids=("99",)),
        }
        assert unique_catalog_entity_type_id(catalog) is None
