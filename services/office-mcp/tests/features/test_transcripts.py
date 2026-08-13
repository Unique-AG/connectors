"""The meeting-transcript chain: the handles, the filter on the wire, and the words that come back.

Every payload is synthesised. A transcript is the most sensitive thing this connector touches, so
nothing here came from a meeting: the speakers are historical figures, the words are invented, and
the ids are obviously fake.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.features import transcripts
from office_mcp.graph_client import GraphForbidden, GraphNotFound

from .conftest import (
    GRAPH_V1,
    JOIN_WEB_URL,
    MEETING_ID,
    TRANSCRIPT_UNATTRIBUTED,
    TRANSCRIPT_VTT,
    meeting_payload,
    transcript_payload,
)

_MEETINGS = "/me/onlineMeetings"
_TRANSCRIPTS = f"/me/onlineMeetings/{MEETING_ID}/transcripts"
_TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0001"
_CONTENT = f"{_TRANSCRIPTS}/{_TRANSCRIPT_ID}/content"

_TENANT_SWITCH_OFF = {
    "error": {
        "code": "Forbidden",
        "message": "Graph API access to transcripts is disabled for this tenant.",
        "innerError": {"code": "GraphAccessToTranscriptsDisabled"},
    }
}

_ATTRIBUTION_OFF = {
    "error": {
        "code": "Forbidden",
        "message": (
            "Speaker-attributed transcript content is disabled for this tenant. Retry with Accept "
            + "'application/vnd.microsoft.graph.transcript+text'."
        ),
        "innerError": {"code": "SpeakerAttributionNotAllowed"},
    }
}


def _handle() -> transcripts.MeetingHandle:
    handle = transcripts.meeting_handle(transcripts.meeting_uri_for(JOIN_WEB_URL) or "")
    assert handle is not None
    return handle


def _resolved(graph: respx.MockRouter, **meeting: object) -> respx.Route:
    return graph.get(_MEETINGS).mock(
        return_value=httpx.Response(200, json={"value": [meeting_payload(**meeting)]})  # pyright: ignore[reportArgumentType]
    )


class TestTheHandleGrammar:
    def test_a_meeting_handle_survives_the_join_url_it_carries(self) -> None:
        """A join URL is full of `:`, `/`, `?`, `&` and `%` and must come back byte-identical:
        Graph matches it against what it stored, character for character."""
        uri = transcripts.meeting_uri_for(JOIN_WEB_URL)
        assert uri is not None

        parsed = transcripts.meeting_handle(uri)

        assert parsed is not None
        assert parsed.join_web_url == JOIN_WEB_URL
        assert "/" not in uri.removeprefix("teams:///meetings/"), (
            "the join URL is one path segment; an unencoded slash would make it several"
        )

    def test_a_transcript_handle_round_trips_both_ids(self) -> None:
        handle = transcripts.TranscriptHandle("MSo1N2Y5:ZGFjYw==", "MSMjMCMj/0001")

        parsed = transcripts.transcript_handle(handle.uri)

        assert parsed is not None
        assert (parsed.meeting_id, parsed.transcript_id) == (
            "MSo1N2Y5:ZGFjYw==",
            "MSMjMCMj/0001",
        )

    @pytest.mark.parametrize(
        "uri",
        [
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
            "teams:///meetings/",
            "teams:///meetings/%20",
            "teams:///meetings/a/b",
            f"teams:///transcripts/{MEETING_ID}/{_TRANSCRIPT_ID}",
            JOIN_WEB_URL,
            "",
        ],
    )
    def test_what_is_not_a_meeting_handle(self, uri: str) -> None:
        """A message handle is not a meeting handle and a transcript handle is not one either — the
        families are separate because the tools and the permissions behind them are."""
        assert transcripts.meeting_handle(uri) is None

    @pytest.mark.parametrize(
        "uri",
        [
            transcripts.MeetingHandle(JOIN_WEB_URL).uri,
            "teams:///transcripts/only-one-id",
            "teams:///transcripts//a",
            "teams:///transcripts/a/%20",
            "teams:///transcripts/a/b/c",
        ],
    )
    def test_what_is_not_a_transcript_handle(self, uri: str) -> None:
        assert transcripts.transcript_handle(uri) is None

    @pytest.mark.parametrize("join_web_url", [None, "", "   "])
    def test_no_join_url_means_no_handle_rather_than_an_empty_one(
        self, join_web_url: str | None
    ) -> None:
        """The case the design has to survive: Graph gives a meeting chat no join URL, so there is
        no route to its transcripts and nothing may pretend otherwise."""
        assert transcripts.meeting_uri_for(join_web_url) is None


class TestTheFilterOnTheWire:
    """The bug class this piece exists not to repeat: `teams-mcp` sends a raw join URL and gets
    `200 OK` with an empty `value` — a silent "meeting not found" — for any URL carrying `&` or `#`.
    """

    async def test_the_join_url_is_percent_encoded_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))

        _ = await transcripts.list_meeting_transcripts(
            client, handle=_handle(), started_after=None, started_before=None, limit=20
        )

        url = route.calls.last.request.url
        # One decode of the wire form must give back exactly the URL Graph stored, inside an OData
        # literal — that is what "encoded once" means, and it is what Graph compares against.
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
        """`#` is the worst of these: URL parsers treat it as a fragment and drop everything after
        it before the request is sent, so a filter built without encoding arrives truncated."""
        route = graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))

        _ = await transcripts.list_meeting_transcripts(
            client,
            handle=transcripts.MeetingHandle(join_web_url),
            started_after=None,
            started_before=None,
            limit=20,
        )

        assert route.calls.last.request.url.params["$filter"] == f"JoinWebUrl eq '{join_web_url}'"

    async def test_a_quote_in_the_join_url_is_doubled_and_cannot_close_the_literal(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """OData escapes a quote inside a string literal by doubling it. Percent-encoding it instead
        would have Graph decode it back to a quote that ends the literal — a 400 at best, and an
        injected predicate at worst."""
        route = graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))

        _ = await transcripts.list_meeting_transcripts(
            client,
            handle=transcripts.MeetingHandle("https://x.invalid/a'/b' or JoinWebUrl ne 'z"),
            started_after=None,
            started_before=None,
            limit=20,
        )

        assert (
            route.calls.last.request.url.params["$filter"]
            == "JoinWebUrl eq 'https://x.invalid/a''/b'' or JoinWebUrl ne ''z'"
        )


class TestNoMatchIsNotAnError:
    async def test_an_empty_collection_is_its_own_answer(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph documents this filter as answering `200 OK` with an empty `value` when nothing
        matches — never a 404 — so "no such meeting" is a status and not an exception, and the
        transcript listing is never even attempted."""
        graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))
        listing = graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(200, json={"value": [transcript_payload()]})
        )

        found = await transcripts.list_meeting_transcripts(
            client, handle=_handle(), started_after=None, started_before=None, limit=20
        )

        assert found.status == "meeting_not_found"
        assert found.meeting_id is None
        assert found.transcripts == []
        assert found.truncated is False
        assert not listing.called, "there is no meeting to list transcripts of"

    async def test_a_404_is_still_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The distinction the empty collection exists to be told apart from."""
        graph.get(_MEETINGS).mock(
            return_value=httpx.Response(404, json={"error": {"code": "NotFound", "message": "no"}})
        )

        with pytest.raises(GraphNotFound):
            _ = await transcripts.list_meeting_transcripts(
                client, handle=_handle(), started_after=None, started_before=None, limit=20
            )


class TestTheThreeAbsences:
    """Nothing came back — and a model must do three different things about it."""

    async def test_the_tenant_switch_is_a_refusal_and_not_an_empty_answer(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`EnableGraphTranscriptAccess` is off, which no permission and no argument can work
        around. It has to reach the tool layer as a failure carrying the inner code, because that
        code is the only thing distinguishing it from an ordinary 403 about a permission."""
        _resolved(graph)
        graph.get(_TRANSCRIPTS).mock(return_value=httpx.Response(403, json=_TENANT_SWITCH_OFF))

        with pytest.raises(GraphForbidden) as raised:
            _ = await transcripts.list_meeting_transcripts(
                client, handle=_handle(), started_after=None, started_before=None, limit=20
            )

        assert raised.value.inner_code == "GraphAccessToTranscriptsDisabled"

    async def test_a_meeting_long_over_with_nothing_in_it_was_never_transcribed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        ended = datetime.now(UTC) - timedelta(days=9)
        _resolved(graph, end=ended.isoformat())
        graph.get(_TRANSCRIPTS).mock(return_value=httpx.Response(200, json={"value": []}))

        found = await transcripts.list_meeting_transcripts(
            client, handle=_handle(), started_after=None, started_before=None, limit=20
        )

        assert found.status == "not_transcribed"
        assert found.meeting_id == MEETING_ID, "the meeting resolved; it just has no transcript"

    @pytest.mark.parametrize(
        "ended",
        [
            datetime.now(UTC) - timedelta(minutes=5),
            datetime.now(UTC) + timedelta(hours=1),
            None,
        ],
        ids=["just-ended", "still-running", "no-end-time"],
    )
    async def test_a_meeting_that_just_ended_is_not_ready_rather_than_never_transcribed(
        self, client: GraphServiceClient, graph: respx.MockRouter, ended: datetime | None
    ) -> None:
        """The two empty answers are the same bytes from Graph and the opposite advice: wait, or
        stop. A meeting Graph gave no end time for counts as "wait", because nothing says
        transcription has finished and one wasted call is cheaper than a wrong answer.
        """
        _resolved(graph, end=ended.isoformat() if ended is not None else None)
        graph.get(_TRANSCRIPTS).mock(return_value=httpx.Response(200, json={"value": []}))

        found = await transcripts.list_meeting_transcripts(
            client, handle=_handle(), started_after=None, started_before=None, limit=20
        )

        assert found.status == "not_ready"

    def test_the_allowance_is_generous_enough_to_be_the_safe_side(self) -> None:
        """Microsoft publishes no availability SLA, so the only defensible bias is towards telling
        a caller to wait. A tight window would report a still-processing transcript as one that
        will never exist, which is the one wrong answer a caller cannot detect."""
        assert timedelta(hours=1) <= transcripts.TRANSCRIPT_DELAY_ALLOWANCE


class TestScopingToOneOccurrence:
    async def test_a_series_is_one_meeting_and_a_window_picks_an_occurrence(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A recurring series has one join URL, one meeting id and one transcript collection —
        Graph publishes no occurrence addressing at all — so the only thing separating occurrences
        is when transcription began."""
        _resolved(graph, meeting_type="recurring")
        graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        transcript_payload(
                            transcript_id="week-1", created_at="2026-02-03T14:02:00Z"
                        ),
                        transcript_payload(
                            transcript_id="week-2", created_at="2026-02-10T14:01:00Z"
                        ),
                        transcript_payload(
                            transcript_id="week-3", created_at="2026-02-17T14:04:00Z"
                        ),
                    ]
                },
            )
        )

        found = await transcripts.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=datetime(2026, 2, 10, tzinfo=UTC),
            started_before=datetime(2026, 2, 11, tzinfo=UTC),
            limit=20,
        )

        assert found.meeting_type == "recurring"
        assert [t.transcript_id for t in found.transcripts] == ["week-2"]
        assert found.truncated is False

    async def test_a_window_with_nothing_in_it_is_not_ready_or_not_transcribed_not_an_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _resolved(graph, meeting_type="recurring", end="2026-02-10T15:00:00Z")
        graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(
                200, json={"value": [transcript_payload(created_at="2026-02-03T14:02:00Z")]}
            )
        )

        found = await transcripts.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=datetime(2026, 3, 1, tzinfo=UTC),
            started_before=None,
            limit=20,
        )

        assert found.status == "not_transcribed"
        assert found.transcripts == []

    async def test_transcripts_come_back_newest_first(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph documents no `$orderby` on this collection, so the order it answers in is not a
        contract and the useful one is applied here."""
        _resolved(graph)
        graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        transcript_payload(
                            transcript_id="older", created_at="2026-02-03T14:00:00Z"
                        ),
                        transcript_payload(
                            transcript_id="newer", created_at="2026-02-17T14:00:00Z"
                        ),
                    ]
                },
            )
        )

        found = await transcripts.list_meeting_transcripts(
            client, handle=_handle(), started_after=None, started_before=None, limit=20
        )

        assert [t.transcript_id for t in found.transcripts] == ["newer", "older"]

    async def test_a_full_window_with_more_behind_it_says_so(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _resolved(graph)
        graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        transcript_payload(transcript_id=f"week-{index}") for index in range(2)
                    ],
                    "@odata.nextLink": f"{GRAPH_V1}{_TRANSCRIPTS}?$skiptoken=synthetic",
                },
            )
        )

        found = await transcripts.list_meeting_transcripts(
            client, handle=_handle(), started_after=None, started_before=None, limit=2
        )

        assert found.truncated is True
        assert found.status == "available"

    async def test_a_limit_above_the_ceiling_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await transcripts.list_meeting_transcripts(
                client,
                handle=_handle(),
                started_after=None,
                started_before=None,
                limit=transcripts.MAX_TRANSCRIPTS + 1,
            )

    async def test_each_transcript_carries_a_handle_and_the_link_to_its_recording(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _resolved(graph)
        graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(200, json={"value": [transcript_payload()]})
        )

        found = await transcripts.list_meeting_transcripts(
            client, handle=_handle(), started_after=None, started_before=None, limit=20
        )

        summary = found.transcripts[0]
        assert transcripts.transcript_handle(summary.uri) == transcripts.TranscriptHandle(
            MEETING_ID, _TRANSCRIPT_ID
        )
        assert summary.content_correlation_id == "bc842d7a-2f6e-4b18-a1c7-73ef91d5c8e3"
        assert summary.started_at is not None and summary.ended_at is not None


class TestReadingTheWords:
    async def test_vtt_becomes_speaker_attributed_timestamped_turns(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The whole differentiator, and every parsing trap in one transcript: the `WEBVTT` header,
        a `NOTE` block, cue identifier lines, a voice tag with a class, a cue wrapped over two
        lines, HTML entities, inline markup, an unattributed cue, an empty one, and the negative
        offset Microsoft documents for transcription that started mid-conversation."""
        route = graph.get(_CONTENT).mock(
            return_value=httpx.Response(
                200, content=TRANSCRIPT_VTT.encode(), headers={"content-type": "text/vtt"}
            )
        )

        read = await transcripts.read_transcript(
            client,
            handle=transcripts.TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID),
            offset=0,
            limit=200,
        )

        assert read.speaker_attribution is True
        assert [(turn.speaker, turn.text) for turn in read.turns] == [
            ("Ada Lovelace", "Sorry, joining late & muted."),
            ("Grace Hopper", "We should raise the floor price by three per cent."),
            ("Ada Lovelace", "Agreed <that> works."),
            (None, "Nobody was attributed for this one."),
        ]
        assert read.turns[0].start_seconds == -2.5, "transcription began mid-conversation"
        assert (read.turns[1].start_seconds, read.turns[1].end_seconds) == (16.246, 19.9)
        assert read.turns[3].start_seconds == 3600.0, "an hour in, from the HH:MM:SS form"
        assert read.truncated is False
        assert read.next_offset is None
        assert route.calls.last.request.headers["accept"] == "text/vtt"

    async def test_the_turns_page_without_refusing_a_long_meeting(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_CONTENT).mock(return_value=httpx.Response(200, content=TRANSCRIPT_VTT.encode()))
        handle = transcripts.TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID)

        first = await transcripts.read_transcript(client, handle=handle, offset=0, limit=2)
        second = await transcripts.read_transcript(
            client, handle=handle, offset=first.next_offset or 0, limit=2
        )

        assert (first.truncated, first.next_offset) == (True, 2)
        assert [turn.speaker for turn in first.turns] == ["Ada Lovelace", "Grace Hopper"]
        assert second.truncated is False
        assert second.next_offset is None
        assert [turn.speaker for turn in second.turns] == ["Ada Lovelace", None]

    async def test_a_tenant_that_forbids_speaker_names_degrades_instead_of_failing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph's own documented remedy: ask again for the unattributed format, which succeeds.
        `services/teams-mcp` hardcodes `Accept: text/vtt` and so loses the transcript entirely in
        such a tenant."""
        attempts: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            accept = request.headers["accept"]
            attempts.append(accept)
            if accept == "text/vtt":
                return httpx.Response(403, json=_ATTRIBUTION_OFF)
            return httpx.Response(200, content=TRANSCRIPT_UNATTRIBUTED.encode())

        graph.get(_CONTENT).mock(side_effect=respond)

        read = await transcripts.read_transcript(
            client,
            handle=transcripts.TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID),
            offset=0,
            limit=200,
        )

        assert attempts == ["text/vtt", "application/vnd.microsoft.graph.transcript+text"]
        assert read.speaker_attribution is False
        assert [turn.speaker for turn in read.turns] == [None, None]
        assert read.turns[0].text == "We should raise the floor price by three per cent."
        assert read.turns[0].start_seconds == 16.246, "the timings survive; only the names are gone"

    async def test_the_tenant_switch_is_not_retried_in_another_format(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The other 403 on the same endpoint. Microsoft says there is no request-side workaround,
        so a second request would be a wasted call and the advice for it names an administrator
        rather than a format — which means the retry must be scoped to the inner code, not to 403.
        """
        route = graph.get(_CONTENT).mock(return_value=httpx.Response(403, json=_TENANT_SWITCH_OFF))

        with pytest.raises(GraphForbidden) as raised:
            _ = await transcripts.read_transcript(
                client,
                handle=transcripts.TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID),
                offset=0,
                limit=200,
            )

        assert raised.value.inner_code == "GraphAccessToTranscriptsDisabled"
        assert route.call_count == 1

    async def test_an_empty_transcript_is_no_turns_rather_than_a_blank_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_CONTENT).mock(return_value=httpx.Response(200, content=b"WEBVTT\n\n"))

        read = await transcripts.read_transcript(
            client,
            handle=transcripts.TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID),
            offset=0,
            limit=200,
        )

        assert read.turns == []
        assert read.truncated is False

    async def test_a_limit_above_the_ceiling_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await transcripts.read_transcript(
                client,
                handle=transcripts.TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID),
                offset=0,
                limit=transcripts.MAX_TURNS + 1,
            )
