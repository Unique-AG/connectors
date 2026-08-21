from datetime import date

import httpx
import pytest
import respx
from fastmcp.decorators import get_fastmcp_meta
from fastmcp.tools.function_tool import ToolMeta

from backstop_mcp.backstop_client import BackstopAuthError, BackstopClient
from backstop_mcp.features.activity_history import (
    EntityActivitiesFetchDto,
    EntityActivityDto,
    SearchActivitiesResolvedResponse,
    SearchActivitiesUnavailableResponse,
)
from backstop_mcp.features.activity_history.tools.search_activities import search_activities
from backstop_mcp.server.tools import TOOLS
from tests.features.party_resolver.helpers import ctx_never_elicit
from tests.helpers import BASE_URL, recorded_json_bodies
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

_URL = f"{BASE_URL}/entity-activities"
_PARTY_ID = "354566359"


def _page(*rows: dict[str, object], total: int | None = None) -> httpx.Response:
    return httpx.Response(
        201,
        json={
            "data": {
                "id": 1,
                "type": "entity-activities",
                "attributes": {
                    "totalCount": len(rows) if total is None else total,
                    "results": list(rows),
                },
            }
        },
    )


def _row(row_id: int = 1, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": row_id,
        "type": "Meeting",
        "title": "Catch-up",
        "effectiveDate": "8/20/2026",
        "meetingType": "Phone - Outbound",
        "activityTags": [{"id": 474963, "name": "AT: Dispersion"}],
        "associatedWith": [{"resourceType": "people", "resourceId": _PARTY_ID}],
        "author": {"name": "Asaph Stephen", "id": 3406537},
        "attendees": [{"name": "Ada"}],
        "attachmentsCount": 0,
    }
    return row | overrides


class TestSearchActivities:
    def test_is_registered_and_states_or_tags_and_the_fallback(self) -> None:
        assert search_activities in TOOLS
        meta = get_fastmcp_meta(search_activities)
        assert isinstance(meta, ToolMeta)
        doc = search_activities.__doc__ or ""
        assert "OR" in doc
        assert "Always start here" in doc
        assert "fallback only" in doc
        assert "get_activity_history" in doc
        assert "10000" in doc
        assert "visible to you" in doc

    @pytest.mark.asyncio
    @respx.mock
    async def test_pins_party_bean_or_tags_and_date_window(self, client: BackstopClient) -> None:
        route = respx.post(_URL).mock(return_value=_page(_row(), total=1))

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                search_type="people",
                party_id=_PARTY_ID,
                activity_tag_ids=["474963", "455289"],
                client=client,
            ),
            SearchActivitiesResolvedResponse,
        )

        assert route.call_count == 1
        envelope = object_dict(recorded_json_bodies(route)[0]["data"])
        attributes = object_dict(envelope["attributes"])
        filters = object_dict(attributes["filters"])
        assert filters["associatedWiths"] == [f"PartyBean_{_PARTY_ID}"]
        assert filters["activityTags"] == ["474963", "455289"]
        effective = object_dict(filters["effectiveDate"])
        assert effective["startTimestamp"] == "2024-01-01T00:00:00"
        assert effective["endTimestamp"] == "2026-08-20T23:59:59"
        assert "shouldIncludeDescription" not in attributes
        assert result.resolved is not None
        assert result.resolved.id == _PARTY_ID
        payload = tool_payload(result)
        row = object_dict(object_list(payload["rows"])[0])
        assert row["id"] == "1"
        assert row["effective_date"] == "2026-08-20"
        assert "description" not in row
        assert result.coverage.visible_count == 1
        assert result.coverage.ceiling_hit is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_window_is_resolved_not_failure(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(return_value=_page(total=0))

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2020, 1, 1),
                end_date=date(2020, 1, 2),
                client=client,
            ),
            SearchActivitiesResolvedResponse,
        )

        assert result.rows == ()
        assert result.coverage.visible_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_primary_failure_names_get_activity_history(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(
            return_value=httpx.Response(404, json={"errors": [{"title": "Not Found"}]})
        )

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                client=client,
            ),
            SearchActivitiesUnavailableResponse,
        )

        assert result.fallback_tool == "get_activity_history"
        assert "get_activity_history" in result.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_transport_timeout_also_names_the_fallback(
        self, client: BackstopClient
    ) -> None:
        """A timeout is the likeliest failure of an unbounded-payload UI endpoint.

        `httpx` transport errors are not `BackstopApiError`, so before the broad clause this
        propagated raw and the model was never told which tool to fall back to.
        """
        respx.post(_URL).mock(side_effect=httpx.TimeoutException("read timeout"))

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                client=client,
            ),
            SearchActivitiesUnavailableResponse,
        )

        assert result.fallback_tool == "get_activity_history"
        assert "get_activity_history" in result.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_failure_does_not_become_unavailable(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(return_value=httpx.Response(401, json={"errors": [{"title": "no"}]}))

        with pytest.raises(BackstopAuthError):
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                client=client,
            )

    @pytest.mark.asyncio
    async def test_include_description_on_a_wide_sweep_is_refused(
        self, client: BackstopClient
    ) -> None:
        with pytest.raises(ValueError, match="wide sweep"):
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                include_description=True,
                client=client,
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_aggregate_counts_without_row_bodies(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(
            return_value=_page(
                _row(1, type="Meeting"),
                _row(2, type="Call"),
                _row(3, type="Meeting"),
                total=3,
            )
        )

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                activity_tag_ids=["474963"],
                mode="aggregate",
                group_by="type",
                client=client,
            ),
            SearchActivitiesResolvedResponse,
        )

        assert result.mode == "aggregate"
        assert result.rows == ()
        payload = [object_dict(item) for item in object_list(tool_payload(result)["aggregates"])]
        by_key = {item["key"]: item["count"] for item in payload}
        assert by_key == {"Meeting": 2, "Call": 1}

    @pytest.mark.asyncio
    async def test_include_description_in_aggregate_mode_is_refused(
        self, client: BackstopClient
    ) -> None:
        with pytest.raises(ValueError, match="aggregate"):
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                activity_tag_ids=["474963"],
                include_description=True,
                mode="aggregate",
                group_by="type",
                client=client,
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_saturated_total_count_is_a_floor(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(return_value=_page(_row(), total=10_000))

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                client=client,
            ),
            SearchActivitiesResolvedResponse,
        )

        assert result.coverage.visible_count == 10_000
        assert result.coverage.visible_count_is_floor is True
        assert result.coverage.ceiling_hit is True
        assert result.coverage.truncated is True
        assert result.coverage.disclaimer is not None
        assert "10000" in result.coverage.disclaimer

    @pytest.mark.asyncio
    @respx.mock
    async def test_sparse_fields_omit_unrequested_keys(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(return_value=_page(_row(), total=1))

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                fields=["id", "title"],
                client=client,
            ),
            SearchActivitiesResolvedResponse,
        )

        row = object_dict(object_list(tool_payload(result)["rows"])[0])
        assert row == {"id": "1", "title": "Catch-up"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_html_bodies_are_converted_to_plain_text(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(
            return_value=_page(
                _row(
                    1,
                    shortDescription="Ross Kasarda, Greg Hines&nbsp;",
                    formattedDescription="<p>Discussed <b>dispersion</b>.</p>",
                ),
                total=1,
            )
        )

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                activity_tag_ids=["474963"],
                include_description=True,
                client=client,
            ),
            SearchActivitiesResolvedResponse,
        )

        row = object_dict(object_list(tool_payload(result)["rows"])[0])
        assert "&nbsp;" not in str(row.get("short_description", ""))
        assert "<p>" not in str(row.get("description", ""))
        assert "dispersion" in str(row.get("description", ""))

    @pytest.mark.asyncio
    async def test_inverted_dates_fail_before_a_request(self, client: BackstopClient) -> None:
        with pytest.raises(ValueError, match="start_date"):
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2026, 8, 21),
                end_date=date(2026, 8, 20),
                client=client,
            )

    def test_from_fetch_marks_a_mid_scan_failure_as_partial(self) -> None:
        result = SearchActivitiesResolvedResponse.from_fetch(
            EntityActivitiesFetchDto(
                rows=(EntityActivityDto(id="1", type="Meeting"),),
                total_count=2000,
                rows_dropped=0,
                rows_received=500,
                pages_fetched=1,
                ceiling_clamped=False,
                truncated_by_row_cap=False,
                partial_due_to_error=True,
            ),
            mode="aggregate",
            fields=frozenset(),
            resolved=None,
            ceiling=10_000,
        )

        assert result.coverage.partial_due_to_error is True
        assert result.coverage.truncated is True
        assert result.coverage.disclaimer is not None
        assert "partial" in result.coverage.disclaimer
        assert "Raise max_rows" not in result.coverage.disclaimer
