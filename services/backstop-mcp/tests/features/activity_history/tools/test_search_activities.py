from datetime import date

import httpx
import pytest
import respx
from fastmcp.decorators import get_fastmcp_meta
from fastmcp.exceptions import ToolError
from fastmcp.tools.function_tool import ToolMeta
from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopAuthError, BackstopClient
from backstop_mcp.config import SearchConfig
from backstop_mcp.features.activity_history import (
    EntityActivitiesFetchDto,
    EntityActivityDto,
    SearchActivitiesResolvedResponse,
    SearchActivitiesUnavailableResponse,
)
from backstop_mcp.features.activity_history.tools.search_activities import (
    AttendeeRef,
    search_activities,
)
from backstop_mcp.features.ui_links import BuildEntityLinkUtil
from backstop_mcp.server.tools import TOOLS
from tests.features.activity_history.conftest import (
    make_search_activities_query,
    serve_entity_activities,
)
from tests.features.party_resolver.helpers import ctx_never_elicit, make_resolve_party_query
from tests.helpers import BASE_URL, client_factory, credential, recorded_json_bodies
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

_URL = f"{BASE_URL}/entity-activities"
_PARTY_ID = "354566359"
_SEARCH_CONFIG = SearchConfig(result_size=100)


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
        "activityTags": [{"id": 9001, "name": "XY: Alpha"}],
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
        assert "one year" in doc
        assert "fallback only" in doc
        assert "get_activity_history" in doc
        assert "10000" in doc
        assert "this credential can see" in doc
        assert "get_activity_detail" in doc
        assert "activity_id" in doc
        assert "history email ids do not" in doc

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
                activity_tag_ids=["9001", "9002"],
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
            ),
            SearchActivitiesResolvedResponse,
        )

        assert route.call_count == 1
        envelope = object_dict(recorded_json_bodies(route)[0]["data"])
        attributes = object_dict(envelope["attributes"])
        filters = object_dict(attributes["newFilters"])
        assert "filters" not in attributes
        assert attributes["entityId"] == int(_PARTY_ID)
        assert attributes["resourceType"] == "people"
        tag_filter = object_dict(object_list(filters["activityTags"])[0])
        assert [object_dict(item)["value"] for item in object_list(tag_filter["searchValues"])] == [
            "9001",
            "9002",
        ]
        effective = object_dict(filters["effectiveDate"])
        assert effective["startTimestamp"] == "2024-01-01T00:00:00"
        assert effective["endTimestamp"] == "2026-08-20T23:59:59"
        assert "shouldIncludeDescription" not in attributes
        assert result.resolved is not None
        assert result.resolved.id == _PARTY_ID
        payload = tool_payload(result)
        row = object_dict(object_list(payload["rows"])[0])
        assert row["id"] == "1"
        assert row["activity_id"] == "1"
        assert row["effective_date"] == "2026-08-20"
        assert "description" not in row
        assert result.coverage.visible_count == 1
        assert result.coverage.ceiling_hit is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_url_is_off_by_default_and_arrives_when_selected(
        self, client: BackstopClient
    ) -> None:
        respx.post(_URL).mock(
            return_value=_page(_row(), _row(2, type="Email Blast"), _row(3, type="Note"), total=3)
        )

        async def run(fields: list[str] | None) -> SearchActivitiesResolvedResponse:
            return tool_model(
                await search_activities(
                    ctx_never_elicit(),
                    start_date=date(2024, 1, 1),
                    end_date=date(2026, 8, 20),
                    fields=fields,  # pyright: ignore[reportArgumentType]
                    resolve_party_query=make_resolve_party_query(client),
                    search_activities_query=make_search_activities_query(client),
                    search_config=_SEARCH_CONFIG,
                    build_entity_link_util=BuildEntityLinkUtil(
                        ui_base_url="https://tenant.example.test"
                    ),
                ),
                SearchActivitiesResolvedResponse,
            )

        default_rows = object_list(tool_payload(await run(None))["rows"])
        assert "url" not in object_dict(default_rows[0])

        email_url = (
            "https://tenant.example.test/backstop/crm/collaboration/"
            + "DisplayEmailMessage.action?summaryId=2&showControls=true"
        )
        selected = object_list(tool_payload(await run(["type", "url"]))["rows"])
        assert [object_dict(row).get("url") for row in selected] == [
            "https://tenant.example.test/backstop/activities.jsp/meetings/1",
            email_url,
            "https://tenant.example.test/backstop/activities.jsp/notes/3",
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_window_is_resolved_not_failure(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(return_value=_page(total=0))

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2020, 1, 1),
                end_date=date(2020, 1, 2),
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
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
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
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
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
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
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_reverified_401_names_the_documented_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Credential still works; the activity search refused us — same as a 404."""

        async def instant_sleep(_delay: float) -> None:
            return None

        monkeypatch.setattr("backstop_mcp.backstop_client.client.asyncio.sleep", instant_sleep)

        async def must_not_revoke() -> None:
            raise AssertionError("must not revoke when /system-info still authenticates")

        factory = client_factory()
        client = factory.for_credential(credential(), on_auth_failure=must_not_revoke)
        try:
            respx.post(_URL).mock(
                return_value=httpx.Response(401, json={"errors": [{"title": "no"}]})
            )
            respx.get(f"{BASE_URL}/system-info").mock(return_value=httpx.Response(200, json={}))

            result = tool_model(
                await search_activities(
                    ctx_never_elicit(),
                    start_date=date(2024, 1, 1),
                    end_date=date(2026, 8, 20),
                    resolve_party_query=make_resolve_party_query(client),
                    search_activities_query=make_search_activities_query(client),
                    search_config=_SEARCH_CONFIG,
                ),
                SearchActivitiesUnavailableResponse,
            )

            assert result.fallback_tool == "get_activity_history"
            assert "get_activity_history" in result.message
        finally:
            await factory.aclose()

    @pytest.mark.asyncio
    async def test_include_description_on_a_firm_wide_search_is_refused(
        self, client: BackstopClient
    ) -> None:
        with pytest.raises(ValueError, match="firm-wide search"):
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                include_description=True,
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_aggregate_counts_a_firm_wide_search(self, client: BackstopClient) -> None:
        route = respx.post(_URL).mock(
            return_value=_page(_row(1, type="Meeting"), _row(2, type="Call"), total=2)
        )

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2026, 7, 1),
                end_date=date(2026, 9, 30),
                mode="aggregate",
                group_by="type",
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
            ),
            SearchActivitiesResolvedResponse,
        )

        attributes = object_dict(object_dict(recorded_json_bodies(route)[0]["data"])["attributes"])
        assert "entityId" not in attributes
        payload = [object_dict(item) for item in object_list(tool_payload(result)["aggregates"])]
        assert {item["key"]: item["count"] for item in payload} == {"Meeting": 1, "Call": 1}

    @pytest.mark.asyncio
    @respx.mock
    async def test_attendees_narrow_a_firm_wide_search_once_per_person(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(_URL).mock(return_value=_page(_row(), total=1))

        await search_activities(
            ctx_never_elicit(),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 10, 5),
            attendees=[
                AttendeeRef(party_id="341763143", search_type="people"),
                AttendeeRef(party_id="791446821", search_type="employees"),
                AttendeeRef(party_id="341763143", search_type="contacts"),
            ],
            include_description=True,
            resolve_party_query=make_resolve_party_query(client),
            search_activities_query=make_search_activities_query(client),
            search_config=_SEARCH_CONFIG,
        )

        attributes = object_dict(object_dict(recorded_json_bodies(route)[0]["data"])["attributes"])
        assert "entityId" not in attributes
        assert object_dict(attributes["newFilters"])["attendees"] == [
            {
                "type": 0,
                "searchValues": [
                    {"value": "PartyBean_341763143"},
                    {"value": "PartyBean_791446821"},
                ],
            }
        ]

    def test_an_organization_is_not_an_attendee(self) -> None:
        with pytest.raises(ValidationError):
            AttendeeRef.model_validate({"party_id": "341686787", "search_type": "organizations"})

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
                activity_tag_ids=["9001"],
                mode="aggregate",
                group_by="type",
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
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
                activity_tag_ids=["9001"],
                include_description=True,
                mode="aggregate",
                group_by="type",
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
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
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
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
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
            ),
            SearchActivitiesResolvedResponse,
        )

        row = object_dict(object_list(tool_payload(result)["rows"])[0])
        assert row == {"id": "1", "activity_id": "1", "title": "Catch-up"}

    @pytest.mark.asyncio
    @respx.mock
    async def test_html_bodies_are_converted_to_plain_text(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(
            return_value=_page(
                _row(
                    1,
                    shortDescription="Ada North, Ben West&nbsp;",
                    formattedDescription="<p>Discussed <b>alpha</b>.</p>",
                ),
                total=1,
            )
        )

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                activity_tag_ids=["9001"],
                include_description=True,
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
            ),
            SearchActivitiesResolvedResponse,
        )

        row = object_dict(object_list(tool_payload(result)["rows"])[0])
        assert "&nbsp;" not in str(row.get("short_description", ""))
        assert "<p>" not in str(row.get("description", ""))
        assert "alpha" in str(row.get("description", ""))

    @pytest.mark.asyncio
    @respx.mock
    async def test_rows_mode_returns_one_page_and_resumes_at_the_next(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(_URL).mock(
            side_effect=serve_entity_activities(
                (
                    _row(1, effectiveDate="8/20/2026"),
                    _row(2, effectiveDate="8/19/2026"),
                    _row(3, effectiveDate="8/19/2026"),
                    _row(4, effectiveDate="8/18/2026"),
                    _row(5, effectiveDate="8/17/2026"),
                )
            )
        )

        async def run(cursor: str | None) -> SearchActivitiesResolvedResponse:
            return tool_model(
                await search_activities(
                    ctx_never_elicit(),
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 8, 20),
                    search_type="organizations",
                    party_id=_PARTY_ID,
                    include_description=True,
                    cursor=cursor,
                    resolve_party_query=make_resolve_party_query(client),
                    search_activities_query=make_search_activities_query(client),
                    search_config=SearchConfig(result_size=2),
                ),
                SearchActivitiesResolvedResponse,
            )

        first = await run(None)
        assert [row.id for row in first.rows] == ["1", "2"]
        assert first.continuation is not None
        assert first.coverage.visible_count == 5
        assert first.coverage.truncated is False
        assert first.coverage.ceiling_hit is False

        second = await run(first.continuation.cursor)
        assert [row.id for row in second.rows] == ["3", "4"]
        assert second.continuation is not None
        # Rows mode pages by `result_size`, and the resumed call reads the next page.
        assert [
            object_dict(object_dict(body["data"])["attributes"])["pageNum"]
            for body in recorded_json_bodies(route)
        ] == [1, 2]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_page_that_reaches_the_end_has_no_continuation(
        self, client: BackstopClient
    ) -> None:
        respx.post(_URL).mock(return_value=_page(_row(1), _row(2)))

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2026, 1, 1),
                end_date=date(2026, 8, 20),
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=SearchConfig(result_size=2),
            ),
            SearchActivitiesResolvedResponse,
        )

        assert len(result.rows) == 2
        assert result.continuation is None
        assert "continuation" not in tool_payload(result)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_cursor_from_different_arguments_is_rejected(
        self, client: BackstopClient
    ) -> None:
        respx.post(_URL).mock(side_effect=serve_entity_activities((_row(1), _row(2), _row(3))))

        first = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2026, 1, 1),
                end_date=date(2026, 8, 20),
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=SearchConfig(result_size=2),
            ),
            SearchActivitiesResolvedResponse,
        )
        assert first.continuation is not None

        with pytest.raises(ToolError, match="different search"):
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2026, 2, 1),
                end_date=date(2026, 8, 20),
                cursor=first.continuation.cursor,
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=SearchConfig(result_size=2),
            )

    @pytest.mark.asyncio
    async def test_a_cursor_in_aggregate_mode_is_refused(self, client: BackstopClient) -> None:
        with pytest.raises(ValueError, match="cursor"):
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
                activity_tag_ids=["9001"],
                mode="aggregate",
                group_by="type",
                cursor="anything",
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
            )

    @pytest.mark.asyncio
    @respx.mock
    async def test_aggregate_mode_still_reads_the_whole_set(self, client: BackstopClient) -> None:
        route = respx.post(_URL).mock(
            side_effect=[
                _page(*(_row(row_id) for row_id in range(1, 501)), total=608),
                _page(*(_row(row_id, type="Note") for row_id in range(501, 609)), total=608),
            ]
        )

        result = tool_model(
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2020, 1, 1),
                end_date=date(2026, 9, 30),
                search_type="organizations",
                party_id=_PARTY_ID,
                mode="aggregate",
                group_by="type",
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=SearchConfig(result_size=2),
            ),
            SearchActivitiesResolvedResponse,
        )

        assert route.call_count == 2
        assert {bucket.key: bucket.count for bucket in result.aggregates} == {
            "Meeting": 500,
            "Note": 108,
        }
        assert result.continuation is None
        assert result.coverage.truncated is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_end_date_without_start_date_still_searches(self, client: BackstopClient) -> None:
        route = respx.post(_URL).mock(return_value=_page(_row(), total=1))

        await search_activities(
            ctx_never_elicit(),
            end_date=date(2024, 12, 31),
            resolve_party_query=make_resolve_party_query(client),
            search_activities_query=make_search_activities_query(client),
            search_config=_SEARCH_CONFIG,
        )

        filters = object_dict(object_dict(recorded_json_bodies(route)[0]["data"])["attributes"])
        effective = object_dict(object_dict(filters["newFilters"])["effectiveDate"])
        assert effective["startTimestamp"] == "2023-12-31T00:00:00"
        assert effective["endTimestamp"] == "2024-12-31T23:59:59"

    @pytest.mark.asyncio
    async def test_inverted_dates_fail_before_a_request(self, client: BackstopClient) -> None:
        with pytest.raises(ValueError, match="start_date"):
            await search_activities(
                ctx_never_elicit(),
                start_date=date(2026, 8, 21),
                end_date=date(2026, 8, 20),
                resolve_party_query=make_resolve_party_query(client),
                search_activities_query=make_search_activities_query(client),
                search_config=_SEARCH_CONFIG,
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
                partial_due_to_error=True,
            ),
            mode="aggregate",
            fields=frozenset(),
            resolved=None,
            urls={},
            ceiling=10_000,
        )

        assert result.coverage.partial_due_to_error is True
        assert result.coverage.truncated is True
        assert result.coverage.disclaimer is not None
        assert "partial" in result.coverage.disclaimer
