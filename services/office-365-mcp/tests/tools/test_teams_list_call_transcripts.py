"""`teams_list_call_transcripts`: the window, the listing's quirks, and the chat join."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, GraphNotFound
from office_365_mcp.shared.handles import CallTranscriptHandle
from office_365_mcp.shared.meetings import MAX_ARTIFACT_SCAN
from office_365_mcp.tools import teams_list_call_transcripts as lister

from .conftest import GRAPH_V1, ME, OTHER_USER_ID, SIGNED_IN_USER_ID

_LISTING = r".*/me/adhocCalls/getAllTranscripts\(.*"
_CHAT_ID = "19:synthetic-call-chat@thread.v2"
_CHAT_MESSAGES = r".*/chats/[^/]+/messages.*"

_OWN_TENANT = "00000000-0000-4000-8000-0000000000aa"
_OTHER_TENANT = "00000000-0000-4000-8000-0000000000bb"

_NO_TRANSCRIPTS = {"error": {"code": "NotFound", "message": "UnknownError"}}
_CLOSED_ROUTE = {"error": {"code": "NotFound", "message": "Requested API is not supported"}}


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _person(user_id: str, tenant: str) -> dict[str, object]:
    return {
        "user": {
            "@odata.type": "#microsoft.graph.teamworkUserIdentity",
            "id": user_id,
            "displayName": None,
            "userIdentityType": "aadUser",
            "tenantId": tenant,
        }
    }


def _row(call_id: str, created: datetime) -> dict[str, object]:
    return {
        "id": f"transcript-{call_id}",
        "callId": call_id,
        "meetingId": None,
        "createdDateTime": _iso(created),
        "endDateTime": _iso(created + timedelta(minutes=5)),
        "contentCorrelationId": f"correlation-{call_id}",
        "meetingOrganizer": _person(SIGNED_IN_USER_ID, _OWN_TENANT),
    }


def _event(
    kind: str, call_id: str, created: datetime, *, tenant: str = _OWN_TENANT
) -> dict[str, object]:
    detail: dict[str, object] = {
        "@odata.type": f"#microsoft.graph.{kind}EventMessageDetail",
        "callId": call_id,
    }
    if kind == "callTranscript":
        detail |= {
            "callTranscriptICalUid": None,
            "meetingOrganizer": _person(OTHER_USER_ID, tenant),
        }
    else:
        detail |= {"callEventType": "call", "initiator": _person(OTHER_USER_ID, tenant)}
    return {
        "@odata.type": "#microsoft.graph.chatMessage",
        "id": f"{kind}-{call_id}",
        "messageType": "unknownFutureValue",
        "createdDateTime": _iso(created),
        "lastModifiedDateTime": _iso(created),
        "from": None,
        "body": {"contentType": "html", "content": "<systemEventMessage/>"},
        "eventDetail": detail,
    }


def _page(rows: list[dict[str, object]], *, more: bool = False) -> httpx.Response:
    body: dict[str, object] = {"value": rows}
    if more:
        body["@odata.nextLink"] = f"{GRAPH_V1}/synthetic-next?$skiptoken=synthetic"
    return httpx.Response(200, json=body)


def _signed_in(graph: respx.MockRouter) -> respx.Route:
    """Mocks the signed-in user, and returns the route of the home-tenant lookup."""
    _ = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))
    return graph.get("/organization").mock(
        return_value=httpx.Response(200, json={"value": [{"id": _OWN_TENANT.upper()}]})
    )


def _listing(graph: respx.MockRouter, *pages: httpx.Response) -> respx.Route:
    return graph.route(method="GET", url__regex=_LISTING).mock(side_effect=list(pages))


def _next_pages(graph: respx.MockRouter, *pages: httpx.Response) -> respx.Route:
    return graph.get("/synthetic-next").mock(side_effect=list(pages))


def _chat(graph: respx.MockRouter, *events: dict[str, object]) -> respx.Route:
    return graph.route(method="GET", url__regex=_CHAT_MESSAGES).mock(
        return_value=_page(list(events))
    )


def _function_arguments(route: respx.Route) -> Mapping[str, str]:
    path = unquote(urlsplit(str(route.calls.last.request.url)).path)
    inside = path[path.index("getAllTranscripts(") + len("getAllTranscripts(") : -1]
    return dict(argument.split("=", 1) for argument in inside.split(","))


async def _list(
    client: GraphServiceClient,
    *,
    created_after: date | datetime | None = None,
    created_before: date | datetime | None = None,
    chat_id: str | None = None,
    limit: int = 20,
) -> lister.CallTranscripts:
    return await lister.teams_list_call_transcripts(
        client,
        created_after=created_after,
        created_before=created_before,
        chat_id=chat_id,
        limit=limit,
    )


class TestWindow:
    async def test_dates_cover_whole_utc_days(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        route = _listing(graph, _page([]))

        _ = await _list(client, created_after=date(2026, 3, 2), created_before=date(2026, 3, 8))

        assert _function_arguments(route) == {
            "userId": f"'{SIGNED_IN_USER_ID}'",
            "startDateTime": "2026-03-02T00:00:00Z",
            "endDateTime": "2026-03-08T23:59:59Z",
        }

    async def test_moments_are_sent_unquoted_in_utc(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        route = _listing(graph, _page([]))
        cet = timezone(timedelta(hours=1))

        _ = await _list(
            client,
            created_after=datetime(2026, 3, 2, 9, 30, tzinfo=cet),
            created_before=datetime(2026, 3, 2, 17, 0),
        )

        arguments = _function_arguments(route)
        assert arguments["startDateTime"] == "2026-03-02T08:30:00Z"
        assert arguments["endDateTime"] == "2026-03-02T17:00:00Z"

    async def test_the_default_is_the_last_seven_days(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        route = _listing(graph, _page([]))
        before = datetime.now(UTC).replace(microsecond=0)

        _ = await _list(client)

        arguments = _function_arguments(route)
        start = datetime.fromisoformat(arguments["startDateTime"])
        end = datetime.fromisoformat(arguments["endDateTime"])
        assert end - start == timedelta(days=7)
        assert before <= end <= datetime.now(UTC)

    async def test_a_window_that_runs_backwards_is_refused_before_any_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        route = _listing(graph, _page([]))

        with pytest.raises(ToolError, match="ends before it starts"):
            _ = await _list(client, created_after=date(2026, 3, 8), created_before=date(2026, 3, 2))

        assert not route.called

    async def test_rows_outside_the_window_are_dropped_before_the_limit_cuts(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        inside = datetime(2026, 3, 3, 10, 0, tzinfo=UTC)
        _ = _listing(
            graph,
            _page(
                [_row("call-inside", inside), _row("call-later", datetime(2026, 3, 9, tzinfo=UTC))]
            ),
        )

        found = await _list(
            client, created_after=date(2026, 3, 2), created_before=date(2026, 3, 8), limit=1
        )

        assert [row.call_id for row in found.transcripts] == ["call-inside"]

    async def test_a_future_start_with_no_end_is_refused_before_any_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        route = _listing(graph, _page([]))

        with pytest.raises(ToolError, match="ends before it starts"):
            _ = await _list(client, created_after=datetime.now(UTC) + timedelta(days=1))

        assert not route.called


class TestListing:
    async def test_rows_carry_a_call_transcript_handle_newest_first(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        now = datetime.now(UTC)
        _ = _listing(
            graph,
            _page(
                [
                    _row("call-old", now - timedelta(days=2)),
                    _row("call-new", now - timedelta(hours=1)),
                ]
            ),
        )

        found = await _list(client)

        assert found.status == "available"
        assert [row.call_id for row in found.transcripts] == ["call-new", "call-old"]
        newest = found.transcripts[0]
        assert newest.uri == CallTranscriptHandle("call-new", "transcript-call-new").uri
        assert newest.organizer_id == SIGNED_IN_USER_ID
        assert newest.content_correlation_id == "correlation-call-new"
        assert found.unmatched_calls is None
        assert found.scan_incomplete is False

    async def test_empty_pages_with_next_links_are_followed_to_the_rows(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        listing = _listing(graph, _page([], more=True))
        following = _next_pages(
            graph,
            _page([], more=True),
            _page([_row("call-late", datetime.now(UTC) - timedelta(hours=1))]),
        )

        found = await _list(client)

        assert [row.call_id for row in found.transcripts] == ["call-late"]
        assert "%24top" not in str(listing.calls.last.request.url)
        assert following.call_count == 2

    async def test_a_user_with_no_call_transcripts_is_none_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        _ = _listing(graph, httpx.Response(404, json=_NO_TRANSCRIPTS))

        found = await _list(client)

        assert found.status == "none_found"
        assert found.transcripts == []
        assert found.scan_incomplete is False

    async def test_a_listing_past_the_scan_cap_is_incomplete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        start = datetime.now(UTC) - timedelta(days=1)
        rows = [
            _row(f"call-{index}", start + timedelta(minutes=index))
            for index in range(MAX_ARTIFACT_SCAN + 1)
        ]
        _ = _listing(graph, _page(rows))

        found = await _list(client, limit=1)

        assert found.scan_incomplete is True

    async def test_any_other_404_stays_an_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        _ = _listing(graph, httpx.Response(404, json=_CLOSED_ROUTE))

        with pytest.raises(GraphNotFound):
            _ = await _list(client)


class TestUnmatchedCalls:
    async def test_each_reason_and_matched_calls_left_out(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        now = datetime.now(UTC)
        _ = _listing(graph, _page([_row("call-listed", now - timedelta(hours=5))]))
        chat = _chat(
            graph,
            _event("callTranscript", "call-fresh", now - timedelta(seconds=30)),
            _event(
                "callTranscript", "call-external", now - timedelta(hours=1), tenant=_OTHER_TENANT
            ),
            _event("callEnded", "call-external", now - timedelta(minutes=50)),
            _event("callEnded", "call-untranscribed", now - timedelta(hours=2)),
            _event("callStarted", "call-untranscribed", now - timedelta(hours=2, minutes=10)),
            _event("callTranscript", "call-unexplained", now - timedelta(hours=3)),
            _event("callEnded", "call-listed", now - timedelta(hours=5)),
            _event("callTranscript", "call-listed", now - timedelta(hours=5)),
        )

        found = await _list(client, chat_id=_CHAT_ID)

        assert [(call.call_id, call.reason) for call in found.unmatched_calls or []] == [
            ("call-fresh", "not_ready"),
            ("call-external", "other_organization"),
            ("call-untranscribed", "not_transcribed"),
            ("call-unexplained", "unknown"),
        ]
        assert {call.organizer_id for call in found.unmatched_calls or []} == {OTHER_USER_ID}
        assert unquote(str(chat.calls.last.request.url)).count(_CHAT_ID) == 1

    async def test_another_organization_wins_over_a_fresh_event(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        now = datetime.now(UTC)
        _ = _listing(graph, httpx.Response(404, json=_NO_TRANSCRIPTS))
        _ = _chat(
            graph,
            _event(
                "callTranscript", "call-external", now - timedelta(seconds=20), tenant=_OTHER_TENANT
            ),
        )

        found = await _list(client, chat_id=_CHAT_ID)

        assert found.status == "none_found"
        assert [call.reason for call in found.unmatched_calls or []] == ["other_organization"]

    async def test_an_old_unlisted_transcript_of_our_own_organization_is_unknown(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        _ = _listing(graph, _page([]))
        _ = _chat(
            graph, _event("callTranscript", "call-old", datetime.now(UTC) - timedelta(days=1))
        )

        found = await _list(client, chat_id=_CHAT_ID)

        assert [call.reason for call in found.unmatched_calls or []] == ["unknown"]

    async def test_an_ended_call_without_a_transcript_event_is_not_transcribed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """No callStarted event: the callEnded event alone decides."""
        tenant_lookup = _signed_in(graph)
        _ = _listing(graph, _page([]))
        _ = _chat(graph, _event("callEnded", "call-ended", datetime.now(UTC) - timedelta(hours=1)))

        found = await _list(client, chat_id=_CHAT_ID)

        assert [call.reason for call in found.unmatched_calls or []] == ["not_transcribed"]
        assert not tenant_lookup.called

    async def test_a_call_that_ended_a_moment_ago_is_not_ready(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        _ = _listing(graph, _page([]))
        _ = _chat(
            graph, _event("callEnded", "call-just-ended", datetime.now(UTC) - timedelta(seconds=30))
        )

        found = await _list(client, chat_id=_CHAT_ID)

        assert [call.reason for call in found.unmatched_calls or []] == ["not_ready"]

    async def test_a_call_that_only_started_is_unknown(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        _ = _listing(graph, _page([]))
        _ = _chat(
            graph, _event("callStarted", "call-running", datetime.now(UTC) - timedelta(minutes=5))
        )

        found = await _list(client, chat_id=_CHAT_ID)

        assert [call.reason for call in found.unmatched_calls or []] == ["unknown"]

    async def test_a_chat_past_the_scan_cap_is_incomplete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        _ = _listing(graph, _page([]))
        start = datetime.now(UTC) - timedelta(days=1)
        _ = _chat(
            graph,
            *(
                _event("callEnded", f"call-{index}", start + timedelta(seconds=index))
                for index in range(MAX_SCANNED_ITEMS + 1)
            ),
        )

        found = await _list(client, chat_id=_CHAT_ID)

        assert found.scan_incomplete is True

    async def test_the_chat_is_read_back_to_the_window_start(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _signed_in(graph)
        _ = _listing(graph, _page([]))
        first = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
        chat = graph.route(method="GET", url__regex=_CHAT_MESSAGES).mock(
            return_value=_page([_event("callTranscript", "call-recent", first)], more=True)
        )
        _ = _next_pages(
            graph,
            _page(
                [
                    _event(
                        "callTranscript", "call-earlier", datetime(2026, 3, 3, 9, 0, tzinfo=UTC)
                    ),
                    _event(
                        "callTranscript", "call-before-window", datetime(2026, 3, 1, tzinfo=UTC)
                    ),
                ]
            ),
        )

        found = await _list(
            client,
            created_after=date(2026, 3, 2),
            created_before=date(2026, 3, 8),
            chat_id=_CHAT_ID,
        )

        query = parse_qs(urlsplit(str(chat.calls.last.request.url)).query)
        assert query["$filter"] == [
            "lastModifiedDateTime gt 2026-03-01T23:59:59Z "
            + "and lastModifiedDateTime lt 2026-03-09T23:59:59Z"
        ]
        assert query["$orderby"] == ["lastModifiedDateTime desc"]
        assert [call.call_id for call in found.unmatched_calls or []] == [
            "call-recent",
            "call-earlier",
        ]
