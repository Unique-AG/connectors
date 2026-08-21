"""The meeting vocabulary: the `$filter` that reaches a meeting, and the window that scopes it.

`list_meeting_transcripts`, `list_meeting_recordings` and `read_transcript` all rest on this, so it
is tested here once rather than once per lister. Every payload is synthesised.
"""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.shared import handles, meetings

_MEETINGS = "/me/onlineMeetings"

# Shaped like the ones Graph stores: already-escaped `%3a` and `%40`, a `?context=` query holding
# `%7b` and `%22`, and a trailing `&` parameter. Each breaks a `$filter` encoded wrongly.
JOIN_WEB_URL = (
    "https://teams.microsoft.invalid/l/meetup-join/"
    + "19%3ameeting_TjAwMDAwMDAwMDAwMA%40thread.v2/0"
    + "?context=%7b%22Tid%22%3a%228a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81%22%7d&anon=true"
)


def _handle() -> handles.MeetingHandle:
    handle = handles.meeting_handle(handles.meeting_uri_for(JOIN_WEB_URL) or "")
    assert handle is not None
    return handle


class TestTheFilterOnTheWire:
    """The bug not to repeat: `teams-mcp` sends a raw join URL and gets `200 OK` with an empty
    `value` — a silent "meeting not found" — for any URL carrying `&` or `#`."""

    async def test_the_join_url_is_percent_encoded_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))

        _ = await meetings.resolve_meeting(client, _handle())

        url = route.calls.last.request.url
        # One decode of the wire form must give back the stored URL inside an OData literal.
        assert url.params["$filter"] == f"JoinWebUrl eq '{JOIN_WEB_URL}'"
        raw = url.query.decode()
        assert "%253ameeting" in raw, "an already-escaped `:` has its own `%` escaped"
        assert "%2540thread" in raw, "and so does an already-escaped `@`"
        assert "%26anon%3Dtrue" in raw, "an `&` left raw would split the query and truncate it"
        assert "%2525" not in raw, (
            "encoding it twice compares `%25` against `%` and matches nothing"
        )
        assert raw.count("JoinWebUrl") == 1

    @pytest.mark.parametrize(
        "join_web_url",
        [
            "https://teams.microsoft.invalid/l/meetup-join/19%3ameeting_x%40thread.v2/0#frag",
            "https://teams.microsoft.invalid/meet/1234567890?p=Ab1%2FCd",
            "https://teams.microsoft.invalid/l/meetup-join/19:meeting_y@thread.v2/0",
        ],
    )
    async def test_every_shape_of_join_url_reaches_graph_intact(
        self, client: GraphServiceClient, graph: respx.MockRouter, join_web_url: str
    ) -> None:
        """`#` is the worst: a URL parser treats it as a fragment and drops everything after it
        before the request is sent, so an unencoded filter arrives truncated."""
        route = graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))

        _ = await meetings.resolve_meeting(client, handles.MeetingHandle(join_web_url))

        assert route.calls.last.request.url.params["$filter"] == f"JoinWebUrl eq '{join_web_url}'"

    async def test_a_quote_in_the_join_url_is_doubled_and_cannot_close_the_literal(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """OData escapes a quote inside a literal by doubling it; percent-encoding it instead has
        Graph decode it back to a quote that ends the literal, injecting a predicate."""
        route = graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))

        _ = await meetings.resolve_meeting(
            client, handles.MeetingHandle("https://x.invalid/a'/b' or JoinWebUrl ne 'z")
        )

        assert (
            route.calls.last.request.url.params["$filter"]
            == "JoinWebUrl eq 'https://x.invalid/a''/b'' or JoinWebUrl ne ''z'"
        )

    async def test_no_match_is_an_answer_and_not_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))

        assert await meetings.resolve_meeting(client, _handle()) is None


class TestTheWindowShapesAModelActuallySends:
    """`2026-02-10` and `2026-02-10T14:00:00` both used to reach a comparison between a naive
    datetime and Graph's aware one and raise `TypeError` at the caller. Resolving happens once,
    here, so nothing downstream can meet a naive datetime."""

    def test_a_bound_that_named_no_zone_is_resolved_against_utc_and_not_the_host(self) -> None:
        """Asserted on the resolved instant and not through a filter: a machine whose local zone
        happens to be UTC cannot tell the two readings apart."""
        window = meetings.OccurrenceWindow.of(
            datetime(2026, 2, 10, 9, 0), datetime(2026, 2, 10, 17, 0)
        )

        assert window.started_after == datetime(2026, 2, 10, 9, 0, tzinfo=UTC)
        assert window.started_before == datetime(2026, 2, 10, 17, 0, tzinfo=UTC)

    def test_a_bare_date_is_a_whole_utc_day_and_not_an_empty_span(self) -> None:
        """The same date in both bounds is how one occurrence gets bracketed; resolving both to
        midnight makes it the empty span between one instant and itself."""
        window = meetings.OccurrenceWindow.of(date(2026, 2, 10), date(2026, 2, 10))

        assert window.started_after == datetime(2026, 2, 10, tzinfo=UTC)
        assert window.started_before is not None
        assert datetime(2026, 2, 10, 23, 59, 59, tzinfo=UTC) < window.started_before
        assert window.started_before < datetime(2026, 2, 11, tzinfo=UTC)

    def test_the_allowance_is_generous_enough_to_be_the_safe_side(self) -> None:
        """Microsoft publishes no availability SLA, and a tight window reports a still-processing
        transcript as one that will never exist — the one wrong answer a caller cannot detect."""
        assert timedelta(hours=1) <= meetings.ARTIFACT_DELAY_ALLOWANCE
