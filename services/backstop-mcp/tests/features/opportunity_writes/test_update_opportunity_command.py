"""`UpdateOpportunityCommand`: PATCH payload shape, stage guards, notify-list append."""

from collections.abc import AsyncGenerator
from datetime import date

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.opportunities import OpportunityStageResponse
from backstop_mcp.features.opportunity_writes import (
    UpdatedOpportunityResponse,
    UpdateOpportunityCommand,
    UpdateOpportunityInput,
    get_update_opportunity_command_factory,
)
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    opportunity_stages_service,
    recorded_json_bodies,
    resource,
    system_users_service,
)
from tests.server.tools.helpers import object_dict

_OPPORTUNITY: TypeAdapter[UpdateOpportunityInput] = TypeAdapter(UpdateOpportunityInput)
_ID = "5755101"
_REPRESENTATIVE_ID = "2967455"
_CCED_ID = "2967456"

VOCABULARY: dict[str, OpportunityStageResponse] = {
    stage.id: stage
    for stage in (
        OpportunityStageResponse(id="42478", name="Prospect", closed=False, sort_order=1),
        OpportunityStageResponse(id="42480", name="Project", closed=False, sort_order=2),
        OpportunityStageResponse(id="42482", name="IDD", closed=False, sort_order=3),
        OpportunityStageResponse(id="85446", name="Client Approval", closed=False, sort_order=4),
        OpportunityStageResponse(id="85444", name="Execution", closed=False, sort_order=5),
        OpportunityStageResponse(id="96016", name="Invested", closed=True, sort_order=6),
        OpportunityStageResponse(id="96018", name="Closed", closed=True, sort_order=7),
    )
}

_DERIVED = ("previousStage", "isOpen", "weightedValue", "daysOpen", "closedDate")


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _update(**payload: object) -> UpdateOpportunityInput:
    return _OPPORTUNITY.validate_python(payload)


def make_command(client: BackstopClient) -> UpdateOpportunityCommand:
    return get_update_opportunity_command_factory(
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
                resource(_CCED_ID, "system-users", name="Pat Lee", userName="plee"),
            ],
            "links": {"next": None},
        },
    )


def _opportunity_document(
    opportunity_id: str,
    *,
    stage_id: str | None = "42478",
    **attributes: object,
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
        200,
        json={
            "data": {
                "id": opportunity_id,
                "type": "opportunities",
                "attributes": attributes,
                "relationships": relationships,
            },
            "included": included,
        },
    )


def _two_type_stages_page() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": "s-opp",
                    "type": "opportunity-stages",
                    "attributes": {"name": "Prospect", "closed": False},
                    "relationships": {
                        "opportunityTypes": {"data": [{"type": "entity-types", "id": "16"}]}
                    },
                },
                {
                    "id": "s-other",
                    "type": "opportunity-stages",
                    "attributes": {"name": "Other Pipe", "closed": False},
                    "relationships": {
                        "opportunityTypes": {"data": [{"type": "entity-types", "id": "99"}]}
                    },
                },
            ],
            "links": {"next": None},
        },
    )


def _mock_catalogs() -> None:
    respx.get(f"{BASE_URL}/opportunity-stages").mock(return_value=_stages_page())
    respx.get(f"{BASE_URL}/system-users").mock(return_value=_users_page())


class TestUpdateOpportunityCommand:
    @respx.mock
    async def test_stage_is_patched_as_a_relationship(self, client: BackstopClient) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            side_effect=[
                _opportunity_document(_ID, stage_id="42478"),
                _opportunity_document(_ID, stage_id="42482"),
            ]
        )
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID, stage_id="42482")
        )

        result = await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, stage="IDD")
        )

        assert isinstance(result, UpdatedOpportunityResponse)
        assert result.stage == "IDD"
        assert result.stage_id == "42482"
        assert result.warnings == ()
        stage = object_dict(_relationships(recorded_json_bodies(route)[0])["stage"])
        assert object_dict(stage["data"]) == {"type": "opportunity-stages", "id": "42482"}

    @respx.mock
    async def test_derived_fields_are_never_sent(self, client: BackstopClient) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID, description="was")
        )
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID, description="now")
        )

        await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, description="now")
        )

        attributes = _attributes(recorded_json_bodies(route)[0])
        for key in _DERIVED:
            assert key not in attributes

    @respx.mock
    async def test_only_supplied_fields_appear_in_the_payload(self, client: BackstopClient) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID, name="Koch", requestedAmount=1_000_000)
        )
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID, requestedAmount=2_000_000)
        )

        await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, requested_amount=2_000_000)
        )

        body = recorded_json_bodies(route)[0]
        assert _attributes(body) == {"requestedAmount": 2_000_000}
        assert "relationships" not in _data(body)

    @respx.mock
    async def test_classification_is_sent_as_the_type_attribute(
        self, client: BackstopClient
    ) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_opportunity_document(_ID))
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, classification="Direct")
        )

        body = recorded_json_bodies(route)[0]
        assert _attributes(body) == {"type": "Direct"}
        assert _data(body)["type"] == "opportunities"

    @respx.mock
    async def test_stage_effective_date_is_sent_as_an_attribute(
        self, client: BackstopClient
    ) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_opportunity_document(_ID))
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        await make_command(client).run(
            new_opportunity=_update(
                opportunity_id=_ID, stage="IDD", stage_effective_date="2099-01-15"
            )
        )

        body = recorded_json_bodies(route)[0]
        assert _attributes(body) == {"stageEffectiveDate": "2099-01-15"}

    @respx.mock
    async def test_relationship_pointers_use_json_api_linkage(self, client: BackstopClient) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_opportunity_document(_ID))
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        await make_command(client).run(
            new_opportunity=_update(
                opportunity_id=_ID,
                investor_id="c1",
                product_id="p1",
                primary_contact_id="person1",
                referral_source_id="c2",
                investor_type_id="it1",
            )
        )

        relationships = _relationships(recorded_json_bodies(route)[0])
        assert object_dict(object_dict(relationships["investor"])["data"]) == {
            "type": "contacts",
            "id": "c1",
        }
        assert object_dict(object_dict(relationships["product"])["data"]) == {
            "type": "products",
            "id": "p1",
        }
        assert object_dict(object_dict(relationships["primaryContact"])["data"]) == {
            "type": "people",
            "id": "person1",
        }
        assert object_dict(object_dict(relationships["referralSource"])["data"]) == {
            "type": "contacts",
            "id": "c2",
        }
        assert object_dict(object_dict(relationships["investorType"])["data"]) == {
            "type": "investor-types",
            "id": "it1",
        }

    @respx.mock
    async def test_unknown_stage_name_lists_valid_stages_and_does_not_write(
        self, client: BackstopClient
    ) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_opportunity_document(_ID))
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        with pytest.raises(ToolError, match="Available stages:.*IDD"):
            await make_command(client).run(
                new_opportunity=_update(opportunity_id=_ID, stage="Not A Stage")
            )

        assert route.call_count == 0

    @respx.mock
    async def test_backdated_stage_effective_date_is_rejected_before_writing(
        self, client: BackstopClient
    ) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID, dateEnteredCurrentStage="2026-09-01")
        )
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        with pytest.raises(ToolError, match="dateEnteredCurrentStage"):
            await make_command(client).run(
                new_opportunity=_update(
                    opportunity_id=_ID,
                    stage="IDD",
                    stage_effective_date=date(2026, 6, 1),
                )
            )

        assert route.call_count == 0

    @respx.mock
    async def test_stage_that_does_not_move_is_reported_in_warnings(
        self, client: BackstopClient
    ) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID, stage_id="42478")
        )
        respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID, stage_id="42478")
        )

        result = await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, stage="IDD")
        )

        assert result.stage == "Prospect"
        assert result.stage_id == "42478"
        assert result.warnings
        assert "IDD" in result.warnings[0]
        assert "not applied" in result.warnings[0]

    @respx.mock
    async def test_add_users_to_notify_sends_one_patch(self, client: BackstopClient) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_opportunity_document(_ID))
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, add_users_to_notify=["plee"])
        )

        assert route.call_count == 1
        cced = object_dict(_relationships(recorded_json_bodies(route)[0])["ccedUsers"])
        assert cced["data"] == [{"type": "system-users", "id": _CCED_ID}]

    @respx.mock
    async def test_unknown_notify_logins_are_skipped(self, client: BackstopClient) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_opportunity_document(_ID))
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        result = await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, add_users_to_notify=["plee", "not-a-user"])
        )

        assert route.call_count == 1
        cced = object_dict(_relationships(recorded_json_bodies(route)[0])["ccedUsers"])
        assert cced["data"] == [{"type": "system-users", "id": _CCED_ID}]
        assert any("not-a-user" in warning for warning in result.warnings)

    @respx.mock
    async def test_all_unknown_notify_logins_leave_the_list_untouched(
        self, client: BackstopClient
    ) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_opportunity_document(_ID))
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        result = await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, replace_users_to_notify=["not-a-user"])
        )

        assert route.call_count == 0
        assert any("not-a-user" in warning for warning in result.warnings)

    @respx.mock
    async def test_replace_skips_unknown_logins_and_writes_the_known_ones(
        self, client: BackstopClient
    ) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_opportunity_document(_ID))
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        result = await make_command(client).run(
            new_opportunity=_update(
                opportunity_id=_ID, replace_users_to_notify=["plee", "not-a-user"]
            )
        )

        bodies = recorded_json_bodies(route)
        assert len(bodies) == 2
        assert object_dict(_relationships(bodies[0])["ccedUsers"])["data"] == []
        assert object_dict(_relationships(bodies[1])["ccedUsers"])["data"] == [
            {"type": "system-users", "id": _CCED_ID}
        ]
        assert any("not-a-user" in warning for warning in result.warnings)

    @respx.mock
    async def test_replace_users_to_notify_clears_then_adds(self, client: BackstopClient) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_opportunity_document(_ID))
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, replace_users_to_notify=["plee"])
        )

        bodies = recorded_json_bodies(route)
        assert len(bodies) == 2
        assert object_dict(_relationships(bodies[0])["ccedUsers"])["data"] == []
        assert object_dict(_relationships(bodies[1])["ccedUsers"])["data"] == [
            {"type": "system-users", "id": _CCED_ID}
        ]

    @respx.mock
    async def test_empty_replace_users_to_notify_sends_one_clear_patch(
        self, client: BackstopClient
    ) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_opportunity_document(_ID))
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, replace_users_to_notify=[])
        )

        bodies = recorded_json_bodies(route)
        assert len(bodies) == 1
        assert object_dict(_relationships(bodies[0])["ccedUsers"])["data"] == []

    @respx.mock
    async def test_owner_login_is_resolved_to_a_system_user_id(
        self, client: BackstopClient
    ) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(return_value=_opportunity_document(_ID))
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, owner_login="jdoe")
        )

        representative = object_dict(
            _relationships(recorded_json_bodies(route)[0])["representative"]
        )
        assert object_dict(representative["data"]) == {
            "type": "system-users",
            "id": _REPRESENTATIVE_ID,
        }

    @respx.mock
    async def test_stage_scoped_to_another_entity_type_is_rejected(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/opportunity-stages").mock(return_value=_two_type_stages_page())
        respx.get(f"{BASE_URL}/system-users").mock(return_value=_users_page())
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID, clientDefinedEntityType=16)
        )
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID)
        )

        with pytest.raises(ToolError, match="entity type 16"):
            await make_command(client).run(
                new_opportunity=_update(opportunity_id=_ID, stage="Other Pipe")
            )

        assert route.call_count == 0

    @respx.mock
    async def test_stage_scoped_to_this_entity_type_is_patched(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/opportunity-stages").mock(return_value=_two_type_stages_page())
        respx.get(f"{BASE_URL}/system-users").mock(return_value=_users_page())
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            side_effect=[
                _opportunity_document(_ID, clientDefinedEntityType=16),
                _opportunity_document(_ID, stage_id="s-opp"),
            ]
        )
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID, stage_id="s-opp")
        )

        result = await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, stage="Prospect")
        )

        assert result.warnings == ()
        stage = object_dict(_relationships(recorded_json_bodies(route)[0])["stage"])
        assert object_dict(stage["data"]) == {"type": "opportunity-stages", "id": "s-opp"}

    @respx.mock
    async def test_unscoped_vocabulary_is_valid_for_any_entity_type(
        self, client: BackstopClient
    ) -> None:
        _mock_catalogs()
        respx.get(f"{BASE_URL}/opportunities/{_ID}").mock(
            side_effect=[
                _opportunity_document(_ID, clientDefinedEntityType=16),
                _opportunity_document(_ID, stage_id="42482"),
            ]
        )
        route = respx.patch(f"{BASE_URL}/opportunities/{_ID}").mock(
            return_value=_opportunity_document(_ID, stage_id="42482")
        )

        result = await make_command(client).run(
            new_opportunity=_update(opportunity_id=_ID, stage="IDD")
        )

        assert result.warnings == ()
        stage = object_dict(_relationships(recorded_json_bodies(route)[0])["stage"])
        assert object_dict(stage["data"]) == {"type": "opportunity-stages", "id": "42482"}
