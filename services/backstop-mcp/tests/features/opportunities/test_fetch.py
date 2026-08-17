"""`fetch_opportunities` and the pure pieces it is assembled from.

Fixtures reproduce the shapes measured on the live instance rather than tidied-up ones: a
stage-history entry carries `"relationships": null` and points at its stage through the inline
`{resourceType, resourceId, resourceLink}` format, and the response side-loads fewer stages than
its history references — the case the cached vocabulary exists for.
"""

import logging
from collections.abc import Sequence
from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.opportunities.fetch import (
    OpportunityFetchResult,
    OpportunityStatus,
    date_entered_order_key,
    fetch_opportunities,
    matches_status,
    order_by_date_entered,
    resolve_stage_name,
    stage_names_from_included,
)
from backstop_mcp.features.opportunities.responses import OpportunityResponse
from backstop_mcp.features.opportunities.stages import OpportunityStage
from tests.helpers import BASE_URL, resource

# The instance's whole vocabulary, as `OpportunityStagesService` hands it over.
VOCABULARY: dict[str, OpportunityStage] = {
    stage.id: stage
    for stage in (
        OpportunityStage(id="42478", name="Prospect", closed=False, sort_order=1),
        OpportunityStage(id="42480", name="Project", closed=False, sort_order=2),
        OpportunityStage(id="42482", name="IDD", closed=False, sort_order=3),
        OpportunityStage(id="85446", name="Client Approval", closed=False, sort_order=4),
        OpportunityStage(id="85444", name="Execution", closed=False, sort_order=5),
        OpportunityStage(id="96016", name="Invested", closed=True, sort_order=6),
        OpportunityStage(id="96018", name="Closed", closed=True, sort_order=7),
    )
}

_ENTITY_ID = "341764767"
_OPPORTUNITIES_URL = f"{BASE_URL}/organizations/{_ENTITY_ID}/opportunities"
_NEXT_PAGE = f"/organizations/{_ENTITY_ID}/opportunities?page[offset]=100"


def _opportunity(
    opportunity_id: str,
    *,
    stage_id: str | None = None,
    history: Sequence[str] = (),
    **attributes: object,
) -> dict[str, object]:
    """One `opportunities` resource, with `stage`/`stageHistory` as the relationships they are."""
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


def _history_entry(
    entry_id: str, *, stage_id: str | None, effective_date: str
) -> dict[str, object]:
    """One side-loaded history entry, verbatim: inline stage pointer, `relationships` null.

    `stage_id=None` gives the ref a null `resourceId` — a pointer at a stage nobody can name.
    """
    stage: dict[str, object] = {
        "resourceType": "opportunity-stages",
        "resourceId": stage_id,
        "restricted": False,
    }
    if stage_id is not None:
        stage["resourceLink"] = f"{BASE_URL}/opportunity-stages/{stage_id}"
    return {
        "id": entry_id,
        "type": "opportunity-stage-history",
        "attributes": {
            "stage": stage,
            "opportunity": {"resourceType": "opportunities", "resourceId": "5072909"},
            "effectiveDate": effective_date,
        },
        "relationships": None,
    }


def _side_loaded_stage(stage_id: str) -> dict[str, object]:
    known = VOCABULARY[stage_id]
    return resource(
        stage_id,
        "opportunity-stages",
        name=known.name,
        sortOrder=known.sort_order,
        closed=known.closed,
    )


def _page(
    *resources: dict[str, object],
    included: Sequence[dict[str, object]] = (),
    next_url: str | None = None,
    total_resource_count: int | None = None,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": list(resources),
            "included": list(included),
            "links": {"next": next_url},
            "meta": {"totalResourceCount": total_resource_count},
        },
    )


async def _fetch(
    client: BackstopClient,
    *,
    status: OpportunityStatus = "all",
    vocabulary: dict[str, OpportunityStage] | None = None,
) -> OpportunityFetchResult:
    return await fetch_opportunities(
        client,
        segment="organizations",
        entity_id=_ENTITY_ID,
        status=status,
        vocabulary=VOCABULARY if vocabulary is None else vocabulary,
    )


def _response(
    opportunity_id: str = "1",
    *,
    is_open: bool | None = None,
    entered: date | None = None,
) -> OpportunityResponse:
    return OpportunityResponse(
        id=opportunity_id, is_open=is_open, date_entered_current_stage=entered
    )


class TestTheRequest:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sub_collection_is_walked_side_loading_stage_and_history(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(_OPPORTUNITIES_URL).mock(return_value=_page())

        await _fetch(client)

        params = route.calls.last.request.url.params
        assert params["include"] == "stage,stageHistory"
        assert params["page[limit]"] == "100"
        assert params["page[offset]"] == "0"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_party_with_no_deals_returns_an_empty_result(
        self, client: BackstopClient
    ) -> None:
        respx.get(_OPPORTUNITIES_URL).mock(return_value=_page())

        result = await _fetch(client)

        assert result.opportunities == ()
        assert (result.total, result.open_count, result.closed_count) == (0, 0, 0)

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_whole_next_chain_is_walked_with_no_cap(self, client: BackstopClient) -> None:
        """No cursor is exposed, so stopping early would drop deals nobody could ask for again."""
        route = respx.get(_OPPORTUNITIES_URL).mock(
            side_effect=[
                _page(_opportunity("a"), _opportunity("b"), next_url=_NEXT_PAGE),
                _page(_opportunity("c")),
            ]
        )

        result = await _fetch(client)

        assert route.call_count == 2
        assert result.total == 3


class TestProjection:
    @pytest.mark.asyncio
    @respx.mock
    async def test_the_current_stage_is_named_from_the_side_loaded_resource(
        self, client: BackstopClient
    ) -> None:
        """With an empty vocabulary, so only `included` can be answering."""
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity("5072909", stage_id="42482", name="Koch - CATS Select", isOpen=True),
                included=[_side_loaded_stage("42482")],
            )
        )

        result = await _fetch(client, vocabulary={})

        deal = result.opportunities[0]
        assert deal.stage == "IDD"
        assert deal.stage_id == "42482"

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_current_stage_is_named_from_the_vocabulary_when_not_side_loaded(
        self, client: BackstopClient
    ) -> None:
        """The current stage takes the same ladder as history, not `follow_included` alone."""
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(_opportunity("5072909", stage_id="42478", isOpen=True))
        )

        result = await _fetch(client)

        deal = result.opportunities[0]
        assert deal.stage == "Prospect"
        assert deal.stage_id == "42478"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_current_stage_in_neither_keeps_its_id_and_omits_the_name(
        self, client: BackstopClient
    ) -> None:
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(_opportunity("5072909", stage_id="70707", isOpen=True))
        )

        result = await _fetch(client)

        deal = result.opportunities[0]
        assert deal.stage is None
        assert deal.stage_id == "70707"
        dumped = deal.model_dump()
        assert "stage" not in dumped
        assert dumped["stage_id"] == "70707"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_padded_stage_linkage_id_still_resolves(self, client: BackstopClient) -> None:
        """`BackstopRelationshipRef.id` is not stripped; both stage indexes are keyed stripped."""
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity("5072909", stage_id=" 42482 ", isOpen=True),
                included=[_side_loaded_stage("42482")],
            )
        )

        result = await _fetch(client, vocabulary={})

        deal = result.opportunities[0]
        assert deal.stage == "IDD"
        assert deal.stage_id == "42482"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_stage_side_loaded_on_the_first_page_names_a_deal_on_the_second(
        self, client: BackstopClient
    ) -> None:
        """`included` accumulates across the whole walk, so projection sees every page's stages."""
        respx.get(_OPPORTUNITIES_URL).mock(
            side_effect=[
                _page(
                    _opportunity("page-1", stage_id="42482"),
                    included=[_side_loaded_stage("42482")],
                    next_url=_NEXT_PAGE,
                ),
                _page(_opportunity("page-2", stage_id="42482")),
            ]
        )

        result = await _fetch(client, vocabulary={})

        assert {deal.id: deal.stage for deal in result.opportunities} == {
            "page-1": "IDD",
            "page-2": "IDD",
        }

    @pytest.mark.asyncio
    @respx.mock
    async def test_previous_stage_is_carried_from_the_attribute(
        self, client: BackstopClient
    ) -> None:
        """It names the stage the deal LEFT — 'Client Approval' while it sits in 'IDD'."""
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity(
                    "5755031", stage_id="42482", isOpen=True, previousStage="Client Approval"
                ),
                included=[_side_loaded_stage("42482")],
            )
        )

        result = await _fetch(client)

        assert result.opportunities[0].previous_stage == "Client Approval"
        assert result.opportunities[0].stage == "IDD"

    @pytest.mark.asyncio
    @respx.mock
    async def test_previous_stage_is_absent_for_a_deal_that_has_never_moved(
        self, client: BackstopClient
    ) -> None:
        """Backstop omits the attribute entirely until the first stage change."""
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity("5755031", stage_id="85446", isOpen=True),
                included=[_side_loaded_stage("85446")],
            )
        )

        result = await _fetch(client)

        assert result.opportunities[0].previous_stage is None
        assert result.opportunities[0].stage == "Client Approval"

    @pytest.mark.asyncio
    @respx.mock
    async def test_measured_attributes_are_projected_onto_the_response(
        self, client: BackstopClient
    ) -> None:
        custom_fields = [{"definitionId": 343439, "name": "Status", "value": "Attended"}]
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity(
                    "5072909",
                    stage_id="96016",
                    name="Koch - CATS Select",
                    isOpen=False,
                    probability=1.0,
                    requestedAmount=100000000.0,
                    allocatedAmount=0.0,
                    currencyCode="USD",
                    expectedInvestmentDate="2024-11-12T00:00:00.000-0500",
                    closedDate="2024-11-13T00:00:00.000-0500",
                    daysOpen=216,
                    daysInCurrentStage=640,
                    dateEnteredCurrentStage="2024-11-13T00:00:00.000-0500",
                    regularCustomFieldValues=custom_fields,
                ),
                included=[_side_loaded_stage("96016")],
            )
        )

        result = await _fetch(client)

        deal = result.opportunities[0]
        assert deal.name == "Koch - CATS Select"
        assert deal.is_open is False
        assert deal.probability == 1.0
        assert deal.requested_amount == 100000000.0
        assert deal.allocated_amount == 0.0
        assert deal.currency == "USD"
        assert deal.expected_investment_date == date(2024, 11, 12)
        assert deal.closed_date == date(2024, 11, 13)
        assert deal.days_open == 216
        assert deal.days_in_current_stage == 640
        assert deal.date_entered_current_stage == date(2024, 11, 13)
        assert deal.custom_field_values == tuple(custom_fields)

    @pytest.mark.asyncio
    @respx.mock
    async def test_attributes_outside_the_modelled_subset_do_not_surface(
        self, client: BackstopClient
    ) -> None:
        """`waitlistId`, `isErisa` and the weighted amounts are on the wire, not in scope."""
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity(
                    "5072909",
                    stage_id="96016",
                    name="Koch - CATS Select",
                    waitlistId=2,
                    isErisa=False,
                    weightedValue=100000000.0,
                    weightedAllocatedValue=0.0,
                ),
                included=[_side_loaded_stage("96016")],
            )
        )

        result = await _fetch(client)

        assert set(result.opportunities[0].model_dump()) == {
            "id",
            "name",
            "stage",
            "stage_id",
            "custom_field_values",
            "stage_history",
        }


class TestStageHistory:
    @pytest.mark.asyncio
    @respx.mock
    async def test_an_entry_whose_relationships_are_null_still_parses(
        self, client: BackstopClient
    ) -> None:
        """`relationships: null` is what Backstop sends, and it is not a dict."""
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity("5072909", stage_id="96016", history=["4908995"]),
                included=[
                    _side_loaded_stage("96016"),
                    _history_entry(
                        "4908995", stage_id="96016", effective_date="2024-04-10T00:00:00.000-0400"
                    ),
                ],
            )
        )

        result = await _fetch(client)

        history = result.opportunities[0].stage_history
        assert len(history) == 1
        assert history[0].stage == "Invested"
        assert history[0].effective_date == date(2024, 4, 10)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_stage_missing_from_included_is_named_from_the_vocabulary(
        self, client: BackstopClient
    ) -> None:
        """Measured: 45 history entries referenced 6 stages, of which 3 were side-loaded."""
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity("5072909", stage_id="96016", history=["1", "2"]),
                included=[
                    _side_loaded_stage("96016"),
                    _history_entry(
                        "1", stage_id="42478", effective_date="2024-04-10T00:00:00.000-0400"
                    ),
                    _history_entry(
                        "2", stage_id="96016", effective_date="2024-11-13T00:00:00.000-0500"
                    ),
                ],
            )
        )

        result = await _fetch(client)

        history = result.opportunities[0].stage_history
        assert [change.stage for change in history] == ["Prospect", "Invested"]
        assert [change.stage_id for change in history] == ["42478", "96016"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_stage_in_neither_is_returned_with_the_name_omitted(
        self, client: BackstopClient
    ) -> None:
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity("5072909", stage_id="96016", history=["1"]),
                included=[
                    _side_loaded_stage("96016"),
                    _history_entry(
                        "1", stage_id="70707", effective_date="2024-04-10T00:00:00.000-0400"
                    ),
                ],
            )
        )

        result = await _fetch(client)

        history = result.opportunities[0].stage_history
        assert len(history) == 1
        assert history[0].stage is None
        assert history[0].stage_id == "70707"
        assert history[0].effective_date == date(2024, 4, 10)
        dumped = history[0].model_dump()
        assert "stage" not in dumped
        assert dumped["stage_id"] == "70707"

    @pytest.mark.asyncio
    @respx.mock
    async def test_each_deal_only_gets_the_entries_linked_to_it(
        self, client: BackstopClient
    ) -> None:
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity("5072909", stage_id="96016", history=["1"]),
                _opportunity("5755031", stage_id="42482", history=["2"]),
                included=[
                    _side_loaded_stage("96016"),
                    _side_loaded_stage("42482"),
                    _history_entry(
                        "1", stage_id="96016", effective_date="2024-11-13T00:00:00.000-0500"
                    ),
                    _history_entry(
                        "2", stage_id="42482", effective_date="2025-02-01T00:00:00.000-0500"
                    ),
                ],
            )
        )

        result = await _fetch(client)

        by_id = {deal.id: deal for deal in result.opportunities}
        assert [change.stage for change in by_id["5072909"].stage_history] == ["Invested"]
        assert [change.stage for change in by_id["5755031"].stage_history] == ["IDD"]


class TestStatusFiltering:
    @staticmethod
    def _mixed_page() -> httpx.Response:
        return _page(
            _opportunity("open-1", stage_id="42482", isOpen=True),
            _opportunity("closed-1", stage_id="96016", isOpen=False),
            _opportunity("closed-2", stage_id="96018", isOpen=False),
            included=[
                _side_loaded_stage("42482"),
                _side_loaded_stage("96016"),
                _side_loaded_stage("96018"),
            ],
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_open_returns_only_open_deals(self, client: BackstopClient) -> None:
        respx.get(_OPPORTUNITIES_URL).mock(return_value=self._mixed_page())

        result = await _fetch(client, status="open")

        assert [deal.id for deal in result.opportunities] == ["open-1"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_closed_returns_only_closed_deals(self, client: BackstopClient) -> None:
        respx.get(_OPPORTUNITIES_URL).mock(return_value=self._mixed_page())

        result = await _fetch(client, status="closed")

        assert [deal.id for deal in result.opportunities] == ["closed-1", "closed-2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_all_returns_every_deal(self, client: BackstopClient) -> None:
        respx.get(_OPPORTUNITIES_URL).mock(return_value=self._mixed_page())

        result = await _fetch(client, status="all")

        assert len(result.opportunities) == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_counts_describe_the_whole_set_not_the_filtered_one(
        self, client: BackstopClient
    ) -> None:
        """So an answer about open deals still says how many closed ones exist."""
        respx.get(_OPPORTUNITIES_URL).mock(return_value=self._mixed_page())

        result = await _fetch(client, status="open")

        assert (result.total, result.open_count, result.closed_count) == (3, 1, 2)

    @pytest.mark.asyncio
    @respx.mock
    async def test_total_counts_what_was_fetched_not_what_backstop_claims(
        self, client: BackstopClient
    ) -> None:
        """`meta.totalResourceCount` is untrustworthy here; `total` is what was actually read."""
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity("open-1", isOpen=True),
                _opportunity("closed-1", isOpen=False),
                total_resource_count=97,
            )
        )

        result = await _fetch(client)

        assert result.total == 2


class TestOrdering:
    @pytest.mark.asyncio
    @respx.mock
    async def test_deals_come_back_newest_first_across_a_multi_page_fetch(
        self, client: BackstopClient
    ) -> None:
        """The ordering is over the whole set, which is why no page boundary is exposed."""
        respx.get(_OPPORTUNITIES_URL).mock(
            side_effect=[
                _page(
                    _opportunity("oldest", dateEnteredCurrentStage="2023-02-01"),
                    _opportunity("newest", dateEnteredCurrentStage="2026-05-05"),
                    next_url=_NEXT_PAGE,
                ),
                _page(_opportunity("middle", dateEnteredCurrentStage="2025-01-01")),
            ]
        )

        result = await _fetch(client)

        assert [deal.id for deal in result.opportunities] == ["newest", "middle", "oldest"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_deal_without_a_stage_entry_date_sorts_last(
        self, client: BackstopClient
    ) -> None:
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity("undated"),
                _opportunity("dated", dateEnteredCurrentStage="2020-01-01"),
            )
        )

        result = await _fetch(client)

        assert [deal.id for deal in result.opportunities] == ["dated", "undated"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_unparseable_stage_entry_date_sorts_last_without_failing(
        self, client: BackstopClient
    ) -> None:
        """What the lenient date parsing is for: unreadable, so treated as absent, never newest."""
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity("unreadable", dateEnteredCurrentStage="not-a-date"),
                _opportunity("dated", dateEnteredCurrentStage="2020-01-01"),
            )
        )

        result = await _fetch(client)

        assert [deal.id for deal in result.opportunities] == ["dated", "unreadable"]
        assert result.opportunities[1].date_entered_current_stage is None


class TestMalformedRecords:
    """Records are validated one at a time, so one bad record costs only itself."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_malformed_record_is_dropped_on_its_own_and_the_rest_returned(
        self, client: BackstopClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The reason the page is not deserialized against a typed schema in one pass.

        `regularCustomFieldValues` is the field this was found on in review: a value the model
        cannot read used to fail every opportunity the party has, not just the record carrying it.
        """
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity(
                    "malformed", stage_id="42482", regularCustomFieldValues="not-a-list-of-fields"
                ),
                _opportunity("intact", stage_id="42482", name="Koch - CATS Select", isOpen=True),
                included=[_side_loaded_stage("42482")],
            )
        )

        with caplog.at_level(logging.WARNING):
            result = await _fetch(client)

        assert [deal.id for deal in result.opportunities] == ["intact"]
        assert result.opportunities[0].name == "Koch - CATS Select"
        assert (result.total, result.open_count) == (1, 1)
        assert "opportunities.record.unreadable" in caplog.text

    @pytest.mark.asyncio
    @respx.mock
    async def test_null_custom_field_values_cost_neither_record_nor_page(
        self, client: BackstopClient
    ) -> None:
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity("no-fields", stage_id="42482", regularCustomFieldValues=None),
                _opportunity(
                    "with-fields",
                    stage_id="42482",
                    regularCustomFieldValues=[{"definitionId": 343439, "value": "Attended"}],
                ),
                included=[_side_loaded_stage("42482")],
            )
        )

        result = await _fetch(client)

        by_id = {deal.id: deal for deal in result.opportunities}
        assert by_id["no-fields"].custom_field_values == ()
        assert by_id["with-fields"].custom_field_values == (
            {"definitionId": 343439, "value": "Attended"},
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_history_entry_whose_stage_ref_has_no_id_keeps_its_date(
        self, client: BackstopClient
    ) -> None:
        """An unidentifiable stage is reported as null, not paid for with the move itself."""
        respx.get(_OPPORTUNITIES_URL).mock(
            return_value=_page(
                _opportunity("5072909", stage_id="96016", history=["1", "2"]),
                included=[
                    _side_loaded_stage("96016"),
                    _history_entry(
                        "1", stage_id=None, effective_date="2024-04-10T00:00:00.000-0400"
                    ),
                    _history_entry(
                        "2", stage_id="96016", effective_date="2024-11-13T00:00:00.000-0500"
                    ),
                ],
            )
        )

        result = await _fetch(client)

        history = result.opportunities[0].stage_history
        assert len(history) == 2
        assert history[0].stage is None
        assert history[0].stage_id is None
        assert history[0].effective_date == date(2024, 4, 10)


class TestMatchesStatus:
    def test_all_matches_every_deal(self) -> None:
        assert matches_status(_response(is_open=True), "all")
        assert matches_status(_response(is_open=False), "all")
        assert matches_status(_response(is_open=None), "all")

    def test_open_matches_only_open_deals(self) -> None:
        assert matches_status(_response(is_open=True), "open")
        assert not matches_status(_response(is_open=False), "open")

    def test_closed_matches_only_closed_deals(self) -> None:
        assert matches_status(_response(is_open=False), "closed")
        assert not matches_status(_response(is_open=True), "closed")

    def test_an_unknown_state_matches_neither_open_nor_closed(self) -> None:
        """Filing it under either would be a guess; `all` still returns it."""
        assert not matches_status(_response(is_open=None), "open")
        assert not matches_status(_response(is_open=None), "closed")


class TestOrderingKey:
    def test_dated_deals_come_back_newest_first(self) -> None:
        ordered = order_by_date_entered(
            [
                _response("old", entered=date(2020, 1, 1)),
                _response("new", entered=date(2026, 1, 1)),
                _response("mid", entered=date(2023, 6, 30)),
            ]
        )

        assert [deal.id for deal in ordered] == ["new", "mid", "old"]

    def test_a_missing_date_sorts_after_every_dated_deal(self) -> None:
        ordered = order_by_date_entered(
            [_response("undated"), _response("ancient", entered=date.min)]
        )

        assert [deal.id for deal in ordered] == ["ancient", "undated"]

    def test_deals_sharing_a_date_keep_their_fetch_order(self) -> None:
        same_day = date(2025, 3, 3)
        ordered = order_by_date_entered(
            [_response("first", entered=same_day), _response("second", entered=same_day)]
        )

        assert [deal.id for deal in ordered] == ["first", "second"]

    def test_the_key_flags_whether_a_date_is_present(self) -> None:
        assert date_entered_order_key(_response(entered=date(2025, 1, 1))) == (
            True,
            date(2025, 1, 1),
        )
        assert date_entered_order_key(_response()) == (False, date.min)


class TestResolveStageName:
    def test_a_side_loaded_stage_wins_over_the_vocabulary(self) -> None:
        """The response describes this instance now; the cache may be up to a TTL behind."""
        assert (
            resolve_stage_name("42482", side_loaded={"42482": "Renamed"}, vocabulary=VOCABULARY)
            == "Renamed"
        )

    def test_the_vocabulary_names_a_stage_the_response_did_not_side_load(self) -> None:
        assert resolve_stage_name("42478", side_loaded={}, vocabulary=VOCABULARY) == "Prospect"

    def test_a_stage_in_neither_has_no_name(self) -> None:
        assert resolve_stage_name("70707", side_loaded={}, vocabulary=VOCABULARY) is None

    def test_no_stage_id_has_no_name(self) -> None:
        assert resolve_stage_name(None, side_loaded={"42482": "IDD"}, vocabulary=VOCABULARY) is None


class TestStageNamesFromIncluded:
    def test_every_side_loaded_stage_is_indexed_by_id(self) -> None:
        included = [_side_loaded_stage("42482"), _side_loaded_stage("96016")]

        assert stage_names_from_included(included) == {"42482": "IDD", "96016": "Invested"}

    def test_resources_of_another_type_are_not_indexed(self) -> None:
        """History entries sit in the same `included` array and carry no name at all."""
        included = [
            _history_entry("1", stage_id="42482", effective_date="2024-04-10"),
            _side_loaded_stage("42482"),
        ]

        assert stage_names_from_included(included) == {"42482": "IDD"}

    def test_a_stage_without_a_name_is_skipped(self) -> None:
        unnamed = resource("42482", "opportunity-stages", sortOrder=3)

        assert stage_names_from_included([unnamed]) == {}
