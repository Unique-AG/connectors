"""`get_opportunities_by_ids`: per-id GET, catalog join, not-found, and opt-in history."""

from collections.abc import Sequence

import httpx
import pytest
import respx
from fastmcp.server.dependencies import without_injected_parameters
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.opportunities import (
    MAX_OPPORTUNITY_IDS,
    GetOpportunitiesByIdsResponse,
)
from backstop_mcp.features.opportunities.tools.get_opportunities_by_ids import (
    get_opportunities_by_ids,
)
from backstop_mcp.server.tools import TOOLS
from tests.features.opportunities.conftest import VOCABULARY, make_get_opportunities_by_ids_query
from tests.helpers import (
    BASE_URL,
    recorded_requests,
    resource,
)
from tests.server.tools.helpers import tool_model

_STAGES_URL = f"{BASE_URL}/opportunity-stages"
_DEFINITIONS_URL = f"{BASE_URL}/custom-field-definitions"
_EMPTY_DEFINITIONS: dict[str, object] = {"data": [], "links": {"next": None}}

_INPUT: TypeAdapter[object] = TypeAdapter(without_injected_parameters(get_opportunities_by_ids))


@pytest.fixture(autouse=True)
def _empty_custom_field_definitions() -> None:
    respx.get(_DEFINITIONS_URL).mock(return_value=httpx.Response(200, json=_EMPTY_DEFINITIONS))


def _opportunity(
    opportunity_id: str,
    *,
    stage_id: str | None = None,
    history: Sequence[str] = (),
    **attributes: object,
) -> dict[str, object]:
    relationships: dict[str, object] = {
        "stageHistory": {
            "data": [{"id": entry_id, "type": "opportunity-stage-history"} for entry_id in history]
        }
    }
    if stage_id is not None:
        relationships["stage"] = {"data": {"id": stage_id, "type": "opportunity-stages"}}
    return {
        "id": opportunity_id,
        "type": "opportunities",
        "attributes": attributes,
        "relationships": relationships,
    }


def _document(
    item: dict[str, object], *, included: list[dict[str, object]] | None = None
) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": item, "included": included or []},
    )


def _side_loaded_stage(stage_id: str) -> dict[str, object]:
    known = VOCABULARY[stage_id]
    return resource(
        stage_id,
        "opportunity-stages",
        name=known.name,
        sortOrder=known.sort_order,
        closed=known.closed,
    )


def _history_entry(entry_id: str, *, stage_id: str, effective_date: str) -> dict[str, object]:
    return {
        "id": entry_id,
        "type": "opportunity-stage-history",
        "attributes": {
            "stage": {
                "resourceType": "opportunity-stages",
                "resourceId": stage_id,
                "restricted": False,
                "resourceLink": f"{BASE_URL}/opportunity-stages/{stage_id}",
            },
            "opportunity": {"resourceType": "opportunities", "resourceId": "5755031"},
            "effectiveDate": effective_date,
        },
        "relationships": None,
    }


def _stages_response() -> httpx.Response:
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


def _open_deal() -> dict[str, object]:
    return _opportunity(
        "5755031",
        stage_id="42482",
        history=["4908995"],
        name="Koch - CATS Select",
        isOpen=True,
        previousStage="Client Approval",
        dateEnteredCurrentStage="2026-03-01T00:00:00.000-0500",
        regularCustomFieldValues=[
            {"definitionId": 8648265, "name": "Probability", "value": 0.3},
        ],
    )


def _two_field_deal() -> dict[str, object]:
    return _opportunity(
        "5755031",
        stage_id="42482",
        name="Koch - CATS Select",
        isOpen=True,
        regularCustomFieldValues=[
            {"definitionId": "8648265", "value": 0.3},
            {"definitionId": "1", "value": 50000},
        ],
    )


def _two_field_definitions() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                resource(
                    "8648265",
                    "custom-field-definitions",
                    name="Probability",
                    entityType="OpportunityBean",
                    fieldType="PERCENT",
                ),
                resource(
                    "1",
                    "custom-field-definitions",
                    name="Estimated Fees",
                    entityType="OpportunityBean",
                    fieldType="MONEY",
                ),
            ],
            "links": {"next": None},
        },
    )


def _deal_included() -> list[dict[str, object]]:
    return [
        _side_loaded_stage("42482"),
        _history_entry("4908995", stage_id="42482", effective_date="2026-03-01T00:00:00.000-0500"),
    ]


async def _call(
    client: BackstopClient,
    *,
    ids: Sequence[str],
    include_stage_history: bool = False,
    custom_field_names: Sequence[str] = (),
    custom_field_definition_ids: Sequence[str] = (),
) -> GetOpportunitiesByIdsResponse:
    return tool_model(
        await get_opportunities_by_ids(
            ids=ids,
            include_stage_history=include_stage_history,
            custom_field_names=custom_field_names,
            custom_field_definition_ids=custom_field_definition_ids,
            get_opportunities_by_ids_query=make_get_opportunities_by_ids_query(client),
        ),
        GetOpportunitiesByIdsResponse,
    )


class TestGetOpportunitiesByIds:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_full_records_in_request_order(self, client: BackstopClient) -> None:
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        first = respx.get(f"{BASE_URL}/opportunities/5755031").mock(
            return_value=_document(_open_deal(), included=_deal_included())
        )
        second = respx.get(f"{BASE_URL}/opportunities/5072909").mock(
            return_value=_document(
                _opportunity(
                    "5072909",
                    stage_id="96016",
                    name="Koch - Invested",
                    isOpen=False,
                ),
                included=[_side_loaded_stage("96016")],
            )
        )

        result = await _call(client, ids=["5755031", "5072909"])

        assert first.call_count == 1
        assert second.call_count == 1
        assert [row.id for row in result.opportunities] == ["5755031", "5072909"]
        assert result.opportunities[0].stage == "IDD"
        assert result.opportunities[0].stage_history == ()
        assert result.not_found == ()
        assert result.errors == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_omits_stage_history_unless_asked(self, client: BackstopClient) -> None:
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        route = respx.get(f"{BASE_URL}/opportunities/5755031").mock(
            return_value=_document(_open_deal(), included=_deal_included())
        )

        omitted = await _call(client, ids=["5755031"])
        included = await _call(client, ids=["5755031"], include_stage_history=True)

        params = [request.url.params.get("include") for request in recorded_requests(route.calls)]
        assert params == ["stage", "stage,stageHistory"]
        assert omitted.opportunities[0].stage_history == ()
        assert [change.stage for change in included.opportunities[0].stage_history] == ["IDD"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_reports_a_missing_id_and_keeps_the_rest(self, client: BackstopClient) -> None:
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(f"{BASE_URL}/opportunities/5755031").mock(
            return_value=_document(_open_deal(), included=_deal_included())
        )
        respx.get(f"{BASE_URL}/opportunities/missing").mock(
            return_value=httpx.Response(404, json={"errors": [{"detail": "not found"}]})
        )

        result = await _call(client, ids=["5755031", "missing"])

        assert [row.id for row in result.opportunities] == ["5755031"]
        assert result.not_found == ("missing",)
        assert result.errors == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_survives_one_failing_id(self, client: BackstopClient) -> None:
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(f"{BASE_URL}/opportunities/5755031").mock(
            return_value=_document(_open_deal(), included=_deal_included())
        )
        respx.get(f"{BASE_URL}/opportunities/broken").mock(
            return_value=httpx.Response(500, json={"errors": [{"detail": "boom"}]})
        )

        result = await _call(client, ids=["5755031", "broken"])

        assert [row.id for row in result.opportunities] == ["5755031"]
        assert result.not_found == ()
        assert len(result.errors) == 1
        assert result.errors[0].id == "broken"
        assert result.errors[0].detail == "boom"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_timeout_on_one_id_keeps_the_rest(self, client: BackstopClient) -> None:
        """Only a `concurrency` 429 is retried, so a timeout must not cost the other ids."""
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(f"{BASE_URL}/opportunities/5755031").mock(
            return_value=_document(_open_deal(), included=_deal_included())
        )
        respx.get(f"{BASE_URL}/opportunities/slow").mock(side_effect=httpx.ReadTimeout("timed out"))

        result = await _call(client, ids=["5755031", "slow"])

        assert [row.id for row in result.opportunities] == ["5755031"]
        assert result.not_found == ()
        assert len(result.errors) == 1
        assert result.errors[0].id == "slow"
        assert result.errors[0].detail == "Backstop did not answer for this id"

    @pytest.mark.asyncio
    @respx.mock
    async def test_custom_field_values_are_joined_with_field_type(
        self, client: BackstopClient
    ) -> None:
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(f"{BASE_URL}/opportunities/5755031").mock(
            return_value=_document(_open_deal(), included=_deal_included())
        )
        definitions = respx.get(_DEFINITIONS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "8648265",
                            "custom-field-definitions",
                            name="Probability",
                            entityType="OpportunityBean",
                            fieldType="PERCENT",
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

        result = await _call(client, ids=["5755031"])

        assert definitions.call_count == 1
        values = result.opportunities[0].custom_field_values
        assert len(values) == 1
        assert values[0].name == "Probability"
        assert values[0].field_type == "PERCENT"
        assert values[0].value == 0.3

    @pytest.mark.asyncio
    @respx.mock
    async def test_custom_field_name_filter_keeps_only_that_field(
        self, client: BackstopClient
    ) -> None:
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(f"{BASE_URL}/opportunities/5755031").mock(
            return_value=_document(_two_field_deal(), included=_deal_included())
        )
        respx.get(_DEFINITIONS_URL).mock(return_value=_two_field_definitions())

        result = await _call(client, ids=["5755031"], custom_field_names=["probability"])

        values = result.opportunities[0].custom_field_values
        assert [value.name for value in values] == ["Probability"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_definition_id_filter_keeps_only_that_field(self, client: BackstopClient) -> None:
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(f"{BASE_URL}/opportunities/5755031").mock(
            return_value=_document(_two_field_deal(), included=_deal_included())
        )
        respx.get(_DEFINITIONS_URL).mock(return_value=_two_field_definitions())

        result = await _call(client, ids=["5755031"], custom_field_definition_ids=["1"])

        values = result.opportunities[0].custom_field_values
        assert [value.name for value in values] == ["Estimated Fees"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_custom_field_filters_and_together(self, client: BackstopClient) -> None:
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(f"{BASE_URL}/opportunities/5755031").mock(
            return_value=_document(_two_field_deal(), included=_deal_included())
        )
        respx.get(_DEFINITIONS_URL).mock(return_value=_two_field_definitions())

        both = await _call(
            client,
            ids=["5755031"],
            custom_field_names=["Probability"],
            custom_field_definition_ids=["8648265"],
        )
        disjoint = await _call(
            client,
            ids=["5755031"],
            custom_field_names=["Probability"],
            custom_field_definition_ids=["1"],
        )

        assert [value.name for value in both.opportunities[0].custom_field_values] == [
            "Probability"
        ]
        assert disjoint.opportunities[0].custom_field_values == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_one_catalog_load_covers_the_whole_batch(self, client: BackstopClient) -> None:
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(f"{BASE_URL}/opportunities/5755031").mock(
            return_value=_document(_open_deal(), included=_deal_included())
        )
        respx.get(f"{BASE_URL}/opportunities/5072909").mock(
            return_value=_document(
                _opportunity("5072909", stage_id="96016", name="Koch - Invested", isOpen=False),
                included=[_side_loaded_stage("96016")],
            )
        )
        definitions = respx.get(_DEFINITIONS_URL).mock(
            return_value=httpx.Response(200, json=_EMPTY_DEFINITIONS)
        )

        await _call(client, ids=["5755031", "5072909"])

        assert definitions.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_catalog_failure_keeps_the_deals(self, client: BackstopClient) -> None:
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(f"{BASE_URL}/opportunities/5755031").mock(
            return_value=_document(_open_deal(), included=_deal_included())
        )
        respx.get(_DEFINITIONS_URL).mock(
            return_value=httpx.Response(500, json={"errors": [{"detail": "down"}]})
        )

        result = await _call(client, ids=["5755031"])

        assert result.opportunities[0].id == "5755031"
        assert result.opportunities[0].custom_field_values == ()

    def test_rejects_more_than_fifty_ids(self) -> None:
        with pytest.raises(ValidationError):
            _INPUT.validate_python({"ids": [str(i) for i in range(MAX_OPPORTUNITY_IDS + 1)]})

    def test_rejects_an_empty_id_list(self) -> None:
        with pytest.raises(ValidationError):
            _INPUT.validate_python({"ids": []})

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_rejects_a_blank_id(self, blank: str) -> None:
        with pytest.raises(ValidationError):
            _INPUT.validate_python({"ids": [blank]})

    @pytest.mark.asyncio
    @respx.mock
    async def test_unreadable_document_for_one_id_keeps_the_rest(
        self, client: BackstopClient
    ) -> None:
        respx.get(_STAGES_URL).mock(return_value=_stages_response())
        respx.get(f"{BASE_URL}/opportunities/5755031").mock(
            return_value=_document(_open_deal(), included=_deal_included())
        )
        respx.get(f"{BASE_URL}/opportunities/broken").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        result = await _call(client, ids=["5755031", "broken"])

        assert [row.id for row in result.opportunities] == ["5755031"]
        assert result.not_found == ()
        assert len(result.errors) == 1
        assert result.errors[0].id == "broken"
        assert result.errors[0].detail == "unreadable opportunity document"

    def test_is_registered(self) -> None:
        assert get_opportunities_by_ids in TOOLS

    def test_docstring_names_the_token_cost_and_batching(self) -> None:
        doc = get_opportunities_by_ids.__doc__
        assert doc is not None
        assert "37,000" in doc
        assert "batch" in doc.lower()
        assert "not_found" in doc
