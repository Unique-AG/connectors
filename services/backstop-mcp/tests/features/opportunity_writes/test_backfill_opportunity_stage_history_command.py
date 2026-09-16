"""`BackfillOpportunityStageHistoryCommand`: pointer shape and bulkLoadSummary outcomes."""

from collections.abc import AsyncGenerator
from datetime import date

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from pydantic import TypeAdapter

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.opportunity_writes import (
    BackfillOpportunityStageHistoryCommand,
    BackfillOpportunityStageHistoryInput,
    get_backfill_opportunity_stage_history_command_factory,
)
from tests.helpers import (
    BASE_URL,
    client_factory,
    credential,
    opportunity_stages_service,
    recorded_json_bodies,
    resource,
)
from tests.server.tools.helpers import object_dict, object_list

_BACKFILL: TypeAdapter[BackfillOpportunityStageHistoryInput] = TypeAdapter(
    BackfillOpportunityStageHistoryInput
)
_IDD = "42482"
_PROJECT = "42480"


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def _backfill(*records: dict[str, object]) -> BackfillOpportunityStageHistoryInput:
    return _BACKFILL.validate_python({"records": list(records)})


def make_command(client: BackstopClient) -> BackfillOpportunityStageHistoryCommand:
    return get_backfill_opportunity_stage_history_command_factory(
        client,
        opportunity_stages_service=opportunity_stages_service(client),
    )


def _stages_page() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                resource(_IDD, "opportunity-stages", name="IDD", closed=False),
                resource(_PROJECT, "opportunity-stages", name="Project", closed=False),
            ],
            "links": {"next": None},
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


def _opportunity_document(*, entity_type_id: str | None = None) -> httpx.Response:
    relationships: dict[str, object] = {}
    if entity_type_id is not None:
        relationships["clientDefinedEntityType"] = {
            "data": {"id": entity_type_id, "type": "entity-types"}
        }
    return httpx.Response(
        200,
        json={
            "data": {
                "id": "5755101",
                "type": "opportunities",
                "attributes": {},
                "relationships": relationships,
            }
        },
    )


def _mock_stages_and_opportunities(*, entity_type_id: str | None = None) -> None:
    respx.get(f"{BASE_URL}/opportunity-stages").mock(return_value=_stages_page())
    respx.get(url__regex=rf"{BASE_URL}/opportunities/[^/]+$").mock(
        return_value=_opportunity_document(entity_type_id=entity_type_id)
    )


def _record(opportunity_id: str = "5755101", *, stage: str = "IDD") -> dict[str, object]:
    return {
        "opportunity_id": opportunity_id,
        "stage": stage,
        "effective_date": date(2026, 2, 1),
    }


def _landed(
    *,
    record_id: str,
    opportunity_id: str,
    stage_id: str = _IDD,
) -> dict[str, object]:
    return {
        "id": record_id,
        "effectiveDate": "2026-02-01T00:00:00.000-0400",
        "opportunity": {
            "resourceType": "opportunities",
            "resourceId": opportunity_id,
            "resourceLink": f"https://example.test/opportunities/{opportunity_id}",
            "restricted": False,
        },
        "stage": {
            "resourceType": "opportunity-stages",
            "resourceId": stage_id,
            "resourceLink": f"https://example.test/opportunity-stages/{stage_id}",
            "restricted": False,
        },
    }


def _bulk_document(
    *,
    total: int,
    success: int,
    errors: list[dict[str, object]],
    records: list[dict[str, object]],
) -> httpx.Response:
    return httpx.Response(
        201,
        json={
            "data": {
                "id": None,
                "type": "bulk-opportunity-stage-history",
                "attributes": {
                    "records": records,
                    "bulkLoadSummary": {
                        "totalCount": total,
                        "successCount": success,
                        "errorMessages": errors,
                    },
                },
                "links": "{ }",
            },
            "included": [],
        },
    )


class TestBackfillOpportunityStageHistoryCommand:
    @respx.mock
    async def test_pointers_use_resource_id_and_resource_type(self, client: BackstopClient) -> None:
        _mock_stages_and_opportunities()
        route = respx.post(f"{BASE_URL}/bulk-opportunity-stage-history").mock(
            return_value=_bulk_document(
                total=1,
                success=1,
                errors=[],
                records=[_landed(record_id="1789380940322", opportunity_id="5755101")],
            )
        )

        result = await make_command(client).run(backfill=_backfill(_record()))

        assert result.applied_count == 1
        assert result.records[0].status == "applied"
        body = recorded_json_bodies(route)[0]
        attributes = object_dict(object_dict(body["data"])["attributes"])
        row = object_dict(object_list(attributes["records"])[0])
        assert object_dict(row["opportunity"]) == {
            "resourceId": "5755101",
            "resourceType": "opportunities",
        }
        assert object_dict(row["stage"]) == {
            "resourceId": _IDD,
            "resourceType": "opportunity-stages",
        }

    @respx.mock
    async def test_one_invalid_stage_name_blocks_the_whole_batch(
        self, client: BackstopClient
    ) -> None:
        _mock_stages_and_opportunities()
        route = respx.post(f"{BASE_URL}/bulk-opportunity-stage-history").mock(
            return_value=_bulk_document(total=2, success=2, errors=[], records=[])
        )

        with pytest.raises(ToolError, match="Available stages"):
            await make_command(client).run(
                backfill=_backfill(_record(), {**_record("5755102"), "stage": "Not A Stage"})
            )

        assert route.call_count == 0

    @respx.mock
    async def test_partial_failure_is_reported_per_record(self, client: BackstopClient) -> None:
        _mock_stages_and_opportunities()
        respx.post(f"{BASE_URL}/bulk-opportunity-stage-history").mock(
            return_value=_bulk_document(
                total=2,
                success=1,
                errors=[
                    {
                        "index": 1,
                        "message": "Error load record #1, Resource opportunities not found by id 9",
                    }
                ],
                records=[_landed(record_id="1789380950831", opportunity_id="5755101")],
            )
        )

        result = await make_command(client).run(backfill=_backfill(_record(), _record("9")))

        assert result.total_count == 2
        assert result.applied_count == 1
        assert result.records[0].status == "applied"
        assert result.records[1].status == "failed"
        assert result.records[1].error is not None

    @respx.mock
    async def test_total_failure_on_201_is_not_reported_as_success(
        self, client: BackstopClient
    ) -> None:
        _mock_stages_and_opportunities()
        respx.post(f"{BASE_URL}/bulk-opportunity-stage-history").mock(
            return_value=_bulk_document(
                total=2,
                success=0,
                errors=[{"message": "batch rejected"}],
                records=[],
            )
        )

        result = await make_command(client).run(backfill=_backfill(_record(), _record("5755102")))

        assert result.applied_count == 0
        assert {record.status for record in result.records} == {"failed"}
        assert all(record.error == "batch rejected" for record in result.records)

    @respx.mock
    async def test_unreturned_row_is_not_marked_applied(self, client: BackstopClient) -> None:
        _mock_stages_and_opportunities()
        respx.post(f"{BASE_URL}/bulk-opportunity-stage-history").mock(
            return_value=_bulk_document(
                total=2,
                success=1,
                errors=[],
                records=[_landed(record_id="1", opportunity_id="5755101")],
            )
        )

        result = await make_command(client).run(
            backfill=_backfill(_record(), _record("5755102", stage="Project"))
        )

        assert result.applied_count == 1
        assert result.records[0].status == "applied"
        assert result.records[1].status == "failed"
        assert result.records[1].error is not None

    @respx.mock
    async def test_an_indexed_error_without_a_message_still_fails_the_record(
        self, client: BackstopClient
    ) -> None:
        _mock_stages_and_opportunities()
        respx.post(f"{BASE_URL}/bulk-opportunity-stage-history").mock(
            return_value=_bulk_document(
                total=1,
                success=1,
                errors=[{"index": 0}],
                records=[_landed(record_id="1", opportunity_id="5755101")],
            )
        )

        result = await make_command(client).run(backfill=_backfill(_record()))

        assert result.records[0].status == "failed"
        assert result.applied_count == 0

    @respx.mock
    async def test_an_unattributable_message_is_surfaced_as_a_warning(
        self, client: BackstopClient
    ) -> None:
        _mock_stages_and_opportunities()
        respx.post(f"{BASE_URL}/bulk-opportunity-stage-history").mock(
            return_value=_bulk_document(
                total=1,
                success=1,
                errors=[{"message": "partial commit warning"}],
                records=[_landed(record_id="1", opportunity_id="5755101")],
            )
        )

        result = await make_command(client).run(backfill=_backfill(_record()))

        assert result.records[0].status == "applied"
        assert result.warnings == ("partial commit warning",)

    @respx.mock
    async def test_stage_is_scoped_to_the_opportunity_entity_type(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/opportunity-stages").mock(return_value=_two_type_stages_page())
        respx.get(url__regex=rf"{BASE_URL}/opportunities/[^/]+$").mock(
            return_value=_opportunity_document(entity_type_id="16")
        )
        route = respx.post(f"{BASE_URL}/bulk-opportunity-stage-history")

        with pytest.raises(ToolError, match="entity type 16"):
            await make_command(client).run(backfill=_backfill(_record(stage="Other Pipe")))

        assert route.call_count == 0
