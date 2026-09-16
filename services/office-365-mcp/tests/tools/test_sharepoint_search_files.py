import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import cast

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.tools import sharepoint_search_files

from .conftest import chat_hit, search_response

_DRIVE_ID = "b!SYNTHETICDRIVE0001"

_SITE = "https://contoso.sharepoint.invalid/sites/Finance"


def _file_hit(
    *,
    item_id: str = "01SYNTHETICITEM0001",
    name: str | None = "Budget 2026.xlsx",
    drive_id: str | None = _DRIVE_ID,
    is_folder: bool = False,
) -> dict[str, object]:
    resource: dict[str, object] = {
        "@odata.type": "#microsoft.graph.driveItem",
        "id": item_id,
        "name": name,
        "size": 20481,
        "webUrl": f"{_SITE}/Shared%20Documents/{item_id}",
        "createdDateTime": "2026-02-01T08:00:00Z",
        "lastModifiedDateTime": "2026-03-04T16:12:41Z",
        "lastModifiedBy": {"user": {"displayName": "Ada Lovelace"}},
    }
    if is_folder:
        resource["folder"] = {"childCount": 3}
    else:
        resource["file"] = {
            "mimeType": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        }
    if drive_id is not None:
        resource["parentReference"] = {
            "driveId": drive_id,
            "driveType": "documentLibrary",
            "path": "/drive/root:/Reports/2026",
        }
    return {"hitId": item_id, "rank": 1, "summary": "synthetic snippet", "resource": resource}


def _request(route: respx.Route) -> dict[str, object]:
    body = cast("dict[str, object]", json.loads(route.calls.last.request.content))
    requests = cast("list[dict[str, object]]", body["requests"])
    assert len(requests) == 1, "Graph honours only one searchRequest per call"
    return requests[0]


def _query_string(route: respx.Route) -> str:
    query = cast("dict[str, object]", _request(route)["query"])
    return cast("str", query["queryString"])


def _matching(graph: respx.MockRouter, *hits: dict[str, object], more: bool = False) -> respx.Route:
    return graph.post("/search/query").mock(
        return_value=httpx.Response(
            200, json=search_response(list(hits), more_results_available=more)
        )
    )


class TestTheQueryItSends:
    async def test_it_asks_only_for_drive_items_and_pages_by_offset(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph, _file_hit())

        _ = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", offset=25, limit=10
        )

        request = _request(route)
        assert request["entityTypes"] == ["driveItem"]
        assert (request["from"], request["size"]) == (25, 10)
        assert "fields" not in request, (
            "Graph drops an invalid field silently, and the default projection already carries "
            + "the parentReference the handle is built from"
        )

    async def test_it_costs_one_graph_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph, _file_hit(), _file_hit(item_id="01SYNTHETICITEM0002"))

        _ = await sharepoint_search_files.sharepoint_search_files(
            client,
            query="budget",
            file_type="xlsx",
            path=_SITE,
            modified_after=date(2026, 3, 1),
            modified_before=date(2026, 3, 31),
            offset=0,
            limit=25,
        )

        assert route.call_count == 1
        assert len(graph.calls) == 1, "and no request to any other Graph endpoint either"

    async def test_every_argument_becomes_its_documented_term(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        _ = await sharepoint_search_files.sharepoint_search_files(
            client,
            query="budget",
            file_type="xlsx",
            path=_SITE,
            modified_after=date(2026, 3, 1),
            modified_before=date(2026, 3, 31),
            offset=0,
            limit=25,
        )

        assert _query_string(route) == (
            "budget AND filetype:xlsx "
            + f'AND path:"{_SITE}" '
            + "AND LastModifiedTime>=2026-03-01T00:00:00Z "
            + "AND LastModifiedTime<2026-04-01T00:00:00Z"
        )

    async def test_the_terms_are_joined_with_an_explicit_and(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        _ = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", file_type="docx", offset=0, limit=25
        )

        assert _query_string(route) == "budget AND filetype:docx"

    async def test_a_file_type_travels_bare_and_a_path_is_quoted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        _ = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", file_type="pdf", path=_SITE, offset=0, limit=25
        )

        sent = _query_string(route)
        assert sent.count('"') % 2 == 0, f"the quoting is closable from inside: {sent}"
        assert sent == f'budget AND filetype:pdf AND path:"{_SITE}"'

    async def test_date_bounds_cover_the_days_they_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        _ = await sharepoint_search_files.sharepoint_search_files(
            client,
            query="budget",
            modified_after=date(2026, 3, 1),
            modified_before=date(2026, 3, 31),
            offset=0,
            limit=25,
        )

        assert _query_string(route) == (
            "budget AND LastModifiedTime>=2026-03-01T00:00:00Z "
            + "AND LastModifiedTime<2026-04-01T00:00:00Z"
        )

    async def test_one_date_in_both_bounds_searches_that_single_day(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        _ = await sharepoint_search_files.sharepoint_search_files(
            client,
            query="budget",
            modified_after=date(2026, 3, 4),
            modified_before=date(2026, 3, 4),
            offset=0,
            limit=25,
        )

        assert _query_string(route) == (
            "budget AND LastModifiedTime>=2026-03-04T00:00:00Z "
            + "AND LastModifiedTime<2026-03-05T00:00:00Z"
        )

    async def test_a_moment_bounds_the_second_rather_than_the_day(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        _ = await sharepoint_search_files.sharepoint_search_files(
            client,
            query="budget",
            modified_after=datetime(2026, 3, 4, 9, 0, tzinfo=UTC),
            modified_before=datetime(2026, 3, 4, 17, 0, tzinfo=UTC),
            offset=0,
            limit=25,
        )

        assert _query_string(route) == (
            "budget AND LastModifiedTime>=2026-03-04T09:00:00Z "
            + "AND LastModifiedTime<=2026-03-04T17:00:00Z"
        )

    async def test_a_moment_with_no_zone_is_read_as_utc(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        _ = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", modified_after=datetime(2026, 3, 4, 9, 0), offset=0, limit=25
        )

        assert _query_string(route) == "budget AND LastModifiedTime>=2026-03-04T09:00:00Z"

    async def test_a_moment_east_of_utc_is_converted_rather_than_relabelled(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        _ = await sharepoint_search_files.sharepoint_search_files(
            client,
            query="budget",
            modified_after=datetime(2026, 3, 4, 9, 0, tzinfo=timezone(timedelta(hours=2))),
            offset=0,
            limit=25,
        )

        assert _query_string(route) == "budget AND LastModifiedTime>=2026-03-04T07:00:00Z"

    async def test_a_multi_word_query_reaches_graph_as_words_and_not_as_a_phrase(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        _ = await sharepoint_search_files.sharepoint_search_files(
            client, query="the budget review", offset=0, limit=25
        )

        assert _query_string(route) == "the budget review"

    async def test_a_phrase_the_caller_quoted_themselves_stays_a_phrase(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        _ = await sharepoint_search_files.sharepoint_search_files(
            client, query='2026 "budget review"', offset=0, limit=25
        )

        assert _query_string(route) == '2026 "budget review"'

    @pytest.mark.parametrize(
        "injection",
        [
            "budget OR filetype:docx",
            "LastModifiedTime>2020-01-01",
            'budget" OR path:"',
            "(budget)",
            "-budget",
            "budg*",
        ],
    )
    async def test_a_caller_cannot_smuggle_kql_through_the_free_text(
        self, client: GraphServiceClient, graph: respx.MockRouter, injection: str
    ) -> None:
        route = _matching(graph)

        _ = await sharepoint_search_files.sharepoint_search_files(
            client, query=injection, file_type="docx", offset=0, limit=25
        )

        sent = _query_string(route)
        assert sent.count('"') % 2 == 0, f"the quoting is closable from inside: {sent}"
        words = [
            word
            for index, part in enumerate(sent.split('"'))
            if index % 2 == 0
            for word in part.split()
        ]
        for word in words:
            if word == "AND":
                continue
            assert not set(word) & set(':"<>=()*') or word == "filetype:docx", (
                f"operator left bare in {sent}: {word}"
            )
            assert not word.startswith("-"), f"negation left bare in {sent}: {word}"
            assert word not in {"OR", "NOT", "NEAR", "ONEAR"}, (
                f"boolean left bare in {sent}: {word}"
            )

    async def test_a_file_type_cannot_smuggle_one_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        _ = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", file_type="docx OR filetype:pdf", offset=0, limit=25
        )

        assert _query_string(route) == 'budget AND filetype:"docx OR filetype:pdf"'


class TestAWindowThatHoldsNothing:
    async def test_a_backwards_window_is_refused_before_graph_is_called(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        with pytest.raises(ToolError) as refused:
            _ = await sharepoint_search_files.sharepoint_search_files(
                client,
                query="budget",
                modified_after=date(2026, 3, 31),
                modified_before=date(2026, 3, 1),
                offset=0,
                limit=25,
            )

        assert "runs backwards" in str(refused.value)
        assert route.call_count == 0, "a window that holds nothing costs no Graph request"

    async def test_a_query_with_no_word_in_it_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _matching(graph)

        with pytest.raises(ToolError) as refused:
            _ = await sharepoint_search_files.sharepoint_search_files(
                client, query='" "', offset=0, limit=25
            )

        assert "no word to look for" in str(refused.value)
        assert route.call_count == 0

    async def test_a_limit_above_what_the_schema_allows_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await sharepoint_search_files.sharepoint_search_files(
                client,
                query="budget",
                offset=0,
                limit=sharepoint_search_files.MAX_RESULTS + 1,
            )


class TestTheHandleItMints:
    async def test_a_file_gets_a_file_handle_and_a_folder_gets_a_folder_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _matching(
            graph,
            _file_hit(item_id="01SYNTHETICFILE0001"),
            _file_hit(item_id="01SYNTHETICFOLDER001", name="Reports", is_folder=True),
        )

        found = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", offset=0, limit=25
        )

        assert [item.uri for item in found.files] == [
            "sharepoint:///files/b%21SYNTHETICDRIVE0001/01SYNTHETICFILE0001",
            "sharepoint:///folders/b%21SYNTHETICDRIVE0001/01SYNTHETICFOLDER001",
        ]
        assert [item.is_folder for item in found.files] == [False, True]

    async def test_a_row_carries_the_metadata_a_caller_picks_a_file_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _matching(graph, _file_hit())

        found = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", offset=0, limit=25
        )

        item = found.files[0]
        assert item.name == "Budget 2026.xlsx"
        assert item.size == 20481
        assert item.last_modified_by == "Ada Lovelace"
        assert item.last_modified_at is not None and item.last_modified_at.year == 2026
        assert item.parent_path == "/drive/root:/Reports/2026"
        assert item.drive_type == "documentLibrary"


class TestHitsThisToolCannotUse:
    async def test_a_hit_whose_resource_is_not_a_drive_item_is_skipped(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _matching(graph, chat_hit(), _file_hit(item_id="01SYNTHETICITEM0007"))

        found = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", offset=0, limit=25
        )

        assert [item.name for item in found.files] == ["Budget 2026.xlsx"]

    async def test_a_hit_with_no_drive_id_is_skipped(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _matching(
            graph,
            _file_hit(item_id="01SYNTHETICITEM0008", drive_id=None),
            _file_hit(item_id="01SYNTHETICITEM0009", name="Plan.docx"),
        )

        found = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", offset=0, limit=25
        )

        assert [item.name for item in found.files] == ["Plan.docx"]

    async def test_one_unusable_hit_does_not_cost_the_caller_the_page(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _matching(graph, _file_hit(drive_id=None), chat_hit())

        found = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", offset=0, limit=25
        )

        assert found.files == []


class TestPagingAndItsHonesty:
    async def test_the_next_offset_advances_past_the_hits_graph_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _matching(
            graph,
            *[_file_hit(item_id=f"01SYNTHETICITEM000{index}") for index in range(3)],
            more=True,
        )

        found = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", offset=50, limit=25
        )

        assert found.next_offset == 53
        assert "total" not in sharepoint_search_files.FileSearchResults.model_fields

    async def test_the_next_offset_counts_graphs_hits_not_the_rows_kept(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _matching(
            graph,
            _file_hit(item_id="01SYNTHETICITEM0001", drive_id=None),
            chat_hit(),
            _file_hit(item_id="01SYNTHETICITEM0003"),
            more=True,
        )

        found = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", offset=0, limit=25
        )

        assert len(found.files) == 1
        assert found.next_offset == 3

    async def test_the_last_page_offers_no_next_offset(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _matching(graph, _file_hit(), more=False)

        found = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", offset=0, limit=25
        )

        assert found.next_offset is None

    async def test_a_search_that_matched_nothing_is_an_empty_page_not_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response(None))
        )

        found = await sharepoint_search_files.sharepoint_search_files(
            client, query="nothing-matches-this", offset=0, limit=25
        )

        assert found.files == []
        assert found.next_offset is None

    async def test_a_page_of_no_hits_never_offers_the_offset_it_was_asked_at(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        empty = _matching(graph, more=True)

        stalled = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", offset=25, limit=25
        )

        assert stalled.next_offset is None

        _ = empty.mock(
            return_value=httpx.Response(
                200, json=search_response([_file_hit()], more_results_available=True)
            )
        )
        advanced = await sharepoint_search_files.sharepoint_search_files(
            client, query="budget", offset=25, limit=25
        )

        assert advanced.next_offset is not None and advanced.next_offset > 25


class TestGraphFailures:
    async def test_a_refused_search_surfaces_as_a_permission_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden) as raised:
            _ = await sharepoint_search_files.sharepoint_search_files(
                client, query="budget", offset=0, limit=25
            )

        assert raised.value.status == 403
