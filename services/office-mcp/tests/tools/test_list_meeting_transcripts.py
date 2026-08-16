"""`list_meeting_transcripts`: the window, the order, and the five answers.

The `$filter` that gets this tool to a meeting at all, and the window type it scopes an occurrence
with, are `shared/meetings.py`'s and are tested there — they are promises about the meeting rather
than about its transcripts. What is tested here is this tool's own: which of the five statuses an
empty collection becomes, what the order is promised over, and what one transcript is reported as.

Every payload is synthesised. A transcript is the most sensitive thing this connector touches, so
nothing here came from a meeting: the ids are obviously fake and the domains are `.invalid`.
"""

from datetime import UTC, date, datetime, timedelta, timezone

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import GraphForbidden, GraphNotFound
from office_mcp.shared import handles, meetings
from office_mcp.tools import list_meeting_transcripts as lister

from .conftest import (
    GRAPH_V1,
    JOIN_WEB_URL,
    MEETING_ID,
    meeting_payload,
    transcript_payload,
)

_MEETINGS = "/me/onlineMeetings"
_TRANSCRIPTS = f"/me/onlineMeetings/{MEETING_ID}/transcripts"
_TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0001"

_TENANT_SWITCH_OFF = {
    "error": {
        "code": "Forbidden",
        "message": "Graph API access to transcripts is disabled for this tenant.",
        "innerError": {"code": "GraphAccessToTranscriptsDisabled"},
    }
}

# Central European Time, which February is in: the offset a European caller's "15:00" carries, and
# one hour away from the UTC the same string is read as when it carries no offset at all.
_CET = timezone(timedelta(hours=1))


def _handle() -> handles.MeetingHandle:
    handle = handles.meeting_handle(handles.meeting_uri_for(JOIN_WEB_URL) or "")
    assert handle is not None
    return handle


def _resolved(graph: respx.MockRouter, **meeting: object) -> respx.Route:
    return graph.get(_MEETINGS).mock(
        return_value=httpx.Response(200, json={"value": [meeting_payload(**meeting)]})  # pyright: ignore[reportArgumentType]
    )


def _pages(
    graph: respx.MockRouter, first: list[dict[str, object]], second: list[dict[str, object]]
) -> respx.Route:
    """Graph's own paging: a first page carrying `@odata.nextLink`, then the rest.

    Two real pages rather than one page that links to itself, because the walk follows the cursor
    to the end of the collection (bounded by `MAX_ARTIFACT_SCAN`) rather than stopping as soon as it
    has `limit` items — which is the whole of what makes "newest first" true.
    """
    return graph.get(_TRANSCRIPTS).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "value": first,
                    "@odata.nextLink": f"{GRAPH_V1}{_TRANSCRIPTS}?$skiptoken=synthetic",
                },
            ),
            httpx.Response(200, json={"value": second}),
        ]
    )


# The only meeting shape that outgrows `MAX_ARTIFACT_SCAN`: one occurrence a day, transcribed every
# time, for the better part of a year. Written oldest-first because Graph documents no `$orderby`
# here and answers in an order of its own — this is the order that puts the genuinely newest
# occurrence past the cap, which is the case both promises below have to be exact about.
_DAILY_SERIES_START = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
_PAST_THE_CAP = meetings.MAX_ARTIFACT_SCAN + 60


def _day(index: int) -> datetime:
    """When occurrence `index` of the daily series was transcribed."""
    return _DAILY_SERIES_START + timedelta(days=index)


def _daily_series(graph: respx.MockRouter, *, total: int = _PAST_THE_CAP) -> respx.Route:
    """A meeting with more transcripts than one call reads, in one page Graph answers with."""
    return graph.get(_TRANSCRIPTS).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    transcript_payload(
                        transcript_id=f"day-{index}",
                        created_at=_day(index).isoformat().replace("+00:00", "Z"),
                    )
                    for index in range(total)
                ]
            },
        )
    )


def _weekly_series(graph: respx.MockRouter, *, end: str | None = "2026-02-17T15:00:00Z") -> None:
    """A recurring series as Graph holds it: one meeting, one transcript collection, three weeks.

    Three occurrences in one collection is the whole reason a window exists — Graph publishes no
    occurrence id and no per-occurrence addressing — and `end` is the series-wide `endDateTime`,
    which is the value the verdict must NOT be read off when a window was asked for.
    """
    _resolved(graph, meeting_type="recurring", end=end)
    _ = graph.get(_TRANSCRIPTS).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    transcript_payload(transcript_id="week-1", created_at="2026-02-03T14:02:00Z"),
                    transcript_payload(transcript_id="week-2", created_at="2026-02-10T14:01:00Z"),
                    transcript_payload(transcript_id="week-3", created_at="2026-02-17T14:04:00Z"),
                ]
            },
        )
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

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=None,
            started_before=None,
            limit=20,
            include_scan_completeness=False,
        )

        assert found.status == "meeting_not_found"
        assert found.meeting_id is None
        assert found.transcripts == []
        assert found.scan_incomplete is None, (
            "the completeness of a scan nobody asked about is not reported, and this call made no "
            "scan at all"
        )
        assert not listing.called, "there is no meeting to list transcripts of"

    async def test_a_404_is_still_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The distinction the empty collection exists to be told apart from."""
        graph.get(_MEETINGS).mock(
            return_value=httpx.Response(404, json={"error": {"code": "NotFound", "message": "no"}})
        )

        with pytest.raises(GraphNotFound):
            _ = await lister.list_meeting_transcripts(
                client,
                handle=_handle(),
                started_after=None,
                started_before=None,
                limit=20,
                include_scan_completeness=False,
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
            _ = await lister.list_meeting_transcripts(
                client,
                handle=_handle(),
                started_after=None,
                started_before=None,
                limit=20,
                include_scan_completeness=False,
            )

        assert raised.value.inner_code == "GraphAccessToTranscriptsDisabled"

    async def test_a_meeting_long_over_with_nothing_in_it_was_never_transcribed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        ended = datetime.now(UTC) - timedelta(days=9)
        _resolved(graph, end=ended.isoformat())
        graph.get(_TRANSCRIPTS).mock(return_value=httpx.Response(200, json={"value": []}))

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=None,
            started_before=None,
            limit=20,
            include_scan_completeness=False,
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

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=None,
            started_before=None,
            limit=20,
            include_scan_completeness=False,
        )

        assert found.status == "not_ready"


class TestScopingToOneOccurrence:
    async def test_a_series_is_one_meeting_and_a_window_picks_an_occurrence(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A recurring series has one join URL, one meeting id and one transcript collection —
        Graph publishes no occurrence addressing at all — so the only thing separating occurrences
        is when transcription began."""
        _weekly_series(graph)

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=datetime(2026, 2, 10, tzinfo=UTC),
            started_before=datetime(2026, 2, 11, tzinfo=UTC),
            limit=20,
            include_scan_completeness=False,
        )

        assert found.meeting_type == "recurring"
        assert [t.transcript_id for t in found.transcripts] == ["week-2"]

    async def test_a_window_with_nothing_in_it_is_not_ready_or_not_transcribed_not_an_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _resolved(graph, meeting_type="recurring", end="2026-02-10T15:00:00Z")
        graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(
                200, json={"value": [transcript_payload(created_at="2026-02-03T14:02:00Z")]}
            )
        )

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=datetime(2026, 3, 1, tzinfo=UTC),
            started_before=None,
            limit=20,
            include_scan_completeness=False,
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

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=None,
            started_before=None,
            limit=20,
            include_scan_completeness=False,
        )

        assert [t.transcript_id for t in found.transcripts] == ["newer", "older"]

    async def test_a_window_holding_more_than_the_limit_is_a_full_window_and_a_complete_scan(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The two facts one flag would conflate, told apart.

        More transcripts in the window than `limit` holds: the newest of them come back, and a
        caller sees `limit` of them, which is what "there may be older ones" looks like everywhere
        else here — the remedy being a wider `limit`. What must NOT be reported is a scan that
        stopped short, because none did: the collection was read to the end, so the first entry is
        the meeting's own latest. One flag saying both would put the caveat belonging to a capped
        read on every full window.
        """
        _resolved(graph)
        _pages(
            graph,
            [transcript_payload(transcript_id="week-1", created_at="2026-02-03T14:00:00Z")],
            [transcript_payload(transcript_id="week-2", created_at="2026-02-10T14:00:00Z")],
        )

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=None,
            started_before=None,
            limit=1,
            include_scan_completeness=True,
        )

        assert found.status == "available"
        assert [t.transcript_id for t in found.transcripts] == ["week-2"]
        assert len(found.transcripts) == 1, "a window filled to `limit`: there may be older ones"
        assert found.scan_incomplete is False, "and yet the collection was read to its end"

    async def test_the_newest_are_returned_and_not_the_first_graph_answered_with(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """ "The latest transcript of this series" is the question this tool exists for, and Graph
        answers this collection in an order of its own — it documents no `$orderby` at all. So the
        window is filled from the whole collection and sorted before `limit` cuts it. Cutting first
        and sorting the remainder returns an arbitrary handful sorted among themselves, which reads
        exactly like the right answer: here it would have answered `oldest`.
        """
        _resolved(graph, meeting_type="recurring")
        graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        transcript_payload(
                            transcript_id="oldest", created_at="2026-02-03T14:00:00Z"
                        ),
                        transcript_payload(
                            transcript_id="middle", created_at="2026-02-10T14:00:00Z"
                        ),
                        transcript_payload(
                            transcript_id="newest", created_at="2026-02-17T14:00:00Z"
                        ),
                    ]
                },
            )
        )

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=None,
            started_before=None,
            limit=1,
            include_scan_completeness=False,
        )

        assert [t.transcript_id for t in found.transcripts] == ["newest"]

    async def test_the_newest_is_found_even_when_it_is_on_a_later_page(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The same promise across Graph's own paging: a walk that stopped as soon as it had
        `limit` items would never have seen the newest one."""
        _resolved(graph, meeting_type="recurring")
        _pages(
            graph,
            [transcript_payload(transcript_id="oldest", created_at="2026-02-03T14:00:00Z")],
            [transcript_payload(transcript_id="newest", created_at="2026-02-17T14:00:00Z")],
        )

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=None,
            started_before=None,
            limit=1,
            include_scan_completeness=False,
        )

        assert [t.transcript_id for t in found.transcripts] == ["newest"]

    async def test_a_scan_that_stopped_short_asserts_no_absence(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The answer that would otherwise contradict itself: `not_transcribed` ("retrying will not
        help") alongside "there is more". Both cannot be true, and a caller cannot see which one is
        wrong. A meeting with more transcripts than one call looks through, none of them in the
        window, is `scan_incomplete` — which claims nothing about absence, and which is reported
        whether or not the caller asked about the scan, because an empty answer is worthless
        without it.
        """
        ended = datetime.now(UTC) - timedelta(days=30)
        _resolved(graph, meeting_type="recurring", end=ended.isoformat())
        graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        transcript_payload(
                            transcript_id=f"occurrence-{index}", created_at="2026-02-03T14:00:00Z"
                        )
                        for index in range(meetings.MAX_ARTIFACT_SCAN + 50)
                    ]
                },
            )
        )

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=datetime(2026, 3, 1, tzinfo=UTC),
            started_before=datetime(2026, 3, 2, tzinfo=UTC),
            limit=20,
            include_scan_completeness=False,
        )

        assert found.transcripts == []
        assert found.status == "scan_incomplete", (
            "the one place a scan that stopped short reaches a caller who did not ask: an absence "
            "over a prefix is no absence"
        )
        assert found.scan_incomplete is None, "and still only `status` says it, unless asked"
        assert found.status not in ("not_transcribed", "not_ready"), (
            "a window whose collection was not read to the end settles nothing either way"
        )

    async def test_narrowing_the_window_cannot_reach_past_the_scan_cap(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Why `scan_incomplete` offers no remedy, proved rather than asserted in prose.

        The window is ours: it is applied to the transcripts *after* Graph has answered, because
        Graph documents no filterable date on this collection. So the request goes out bare and the
        same first `MAX_ARTIFACT_SCAN` transcripts are read whatever window was asked for — a wide
        window and a narrow one over the same collection are the same call with the same answer,
        and "narrow it and ask again" would be a loop a model could run forever. Here the narrow
        window even brackets a transcript that genuinely exists (`day-250`), and it is still never
        seen.
        """
        _resolved(graph, meeting_type="recurring")
        listing = _daily_series(graph)

        wide = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=_day(meetings.MAX_ARTIFACT_SCAN).date(),
            started_before=_day(_PAST_THE_CAP - 1).date(),
            limit=20,
            include_scan_completeness=False,
        )
        wide_request = listing.calls.last.request.url
        narrow = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=_day(250).date(),
            started_before=_day(250).date(),
            limit=20,
            include_scan_completeness=False,
        )
        narrow_request = listing.calls.last.request.url

        assert (wide.status, wide.transcripts) == ("scan_incomplete", [])
        assert (narrow.status, narrow.transcripts) == (wide.status, [])
        assert str(wide_request) == str(narrow_request), "two windows, one request"
        for asked in (wide_request, narrow_request):
            assert not {"$filter", "$orderby", "$top"} & set(asked.params), (
                f"the window is applied here, not by Graph: {asked}"
            )

    async def test_the_unreadable_answer_tells_a_caller_to_stop_rather_than_to_retry(self) -> None:
        """The advice a model reads, pinned against the loop it would otherwise be.
        `scan_incomplete` is the one verdict with no caller action behind it, so what it must say
        is that there is nothing to try — not an argument to change, which never terminates."""
        described = str(lister.MeetingTranscripts.model_fields["status"].description)

        assert "There is nothing to try" in described
        assert "Never report this as 'there is no transcript'" in described
        assert "This status is final and cannot be retried" in described
        assert "Narrow `started_after`/`started_before` to the occurrence you mean" not in described

    async def test_past_the_cap_the_newest_returned_is_the_newest_of_what_was_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """ "Newest first" is exact over the transcripts read, and the read stops at the cap.

        A daily series recorded for most of a year has its genuinely newest occurrence past
        `MAX_ARTIFACT_SCAN`, and Graph offers no `$orderby` to ask for it — so asking for 3 gives
        the 3 newest of the 200 that were read, not the 3 newest of the meeting. That is the honest
        answer; calling them "the 3 latest" would be the dishonest one, so the field that says the
        read stopped short is asked for here and asserted alongside it. It is the one thing about
        this answer a caller cannot work out from the answer — three entries for a `limit` of three
        is what an ordinary full window looks like too — which is why it exists at all, and why it
        is opt-in rather than always on.
        """
        _resolved(graph, meeting_type="recurring")
        _daily_series(graph)

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=None,
            started_before=None,
            limit=3,
            include_scan_completeness=True,
        )

        assert found.status == "available"
        assert found.scan_incomplete is True, "the cap was reached, and the answer has to say so"
        returned = [item.transcript_id for item in found.transcripts]
        assert returned == ["day-199", "day-198", "day-197"], "the newest of the ones read"
        assert f"day-{_PAST_THE_CAP - 1}" not in returned, (
            "the meeting's genuinely newest transcript was never read, which is the whole point"
        )

    async def test_a_caller_who_did_not_ask_about_the_scan_is_told_nothing_about_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The same meeting, unasked: the field is null rather than false.

        This is what "opt-in" has to mean for it to be worth anything — a client that does not want
        the signal never sees it, and a null is not a claim that the scan finished. What does not
        change is the read: the same transcripts come back in the same order, so the parameter is
        about the answer's shape and never about the work.
        """
        _resolved(graph, meeting_type="recurring")
        _daily_series(graph)

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=None,
            started_before=None,
            limit=3,
            include_scan_completeness=False,
        )

        assert found.scan_incomplete is None
        assert [item.transcript_id for item in found.transcripts] == [
            "day-199",
            "day-198",
            "day-197",
        ]

    async def test_a_meeting_graph_pages_through_nothing_is_read_to_its_end(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The claim `scan_incomplete` rests on, proved rather than inherited.

        "This meeting has more transcripts than one call reads" is a claim about the meeting, and it
        is only true while a short walk can have been stopped by nothing but a cap. Graph answers
        this collection `[3 + nextLink]`, `[nothing + nextLink]`, `[the newest]`, and the SDK's own
        page walker reads the empty middle page as the end of the collection — which would stop the
        walk one page short of the newest transcript and report a cap it never reached, on a meeting
        with four transcripts. Nothing about a four-transcript meeting is incomplete, so the walk in
        `graph_client/pagination.py` follows an empty page carrying a next link, and this is the
        test that says so from up here where the wrong answer would have been read.
        """
        _resolved(graph, meeting_type="recurring")
        listing = graph.get(_TRANSCRIPTS).mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "value": [
                            transcript_payload(
                                transcript_id=f"week-{index}",
                                created_at=f"2026-02-0{index}T14:00:00Z",
                            )
                            for index in (1, 2, 3)
                        ],
                        "@odata.nextLink": f"{GRAPH_V1}{_TRANSCRIPTS}?$skiptoken=page-2",
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "value": [],
                        "@odata.nextLink": f"{GRAPH_V1}{_TRANSCRIPTS}?$skiptoken=page-3",
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "value": [
                            transcript_payload(
                                transcript_id="week-4", created_at="2026-02-24T14:00:00Z"
                            )
                        ]
                    },
                ),
            ]
        )

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=None,
            started_before=None,
            limit=20,
            include_scan_completeness=True,
        )

        assert [item.transcript_id for item in found.transcripts] == [
            "week-4",
            "week-3",
            "week-2",
            "week-1",
        ], "every page was walked, and the newest is the one behind the empty page"
        assert found.status == "available"
        assert found.scan_incomplete is False, (
            "no cap was reached, so nothing may claim this meeting holds more transcripts than one "
            "call reads"
        )
        assert len(listing.calls) == 3

    async def test_a_short_list_is_not_a_complete_window_when_the_scan_stopped_short(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The same claim the recordings lister proved false of the shared mechanism, checked here
        too because the sentence was in both descriptions.

        "Fewer than `limit` means these are the whole window" holds wherever a walk reaches the end
        of its collection, and this walk stops at `MAX_ARTIFACT_SCAN` instead. A meeting past the
        cap answers with two transcripts against a `limit` of twenty while transcripts of that same
        window sit among the ones never read — a short list meaning the opposite of what the
        convention says. Only `scan_incomplete` separates the two cases.
        """
        _resolved(graph, meeting_type="recurring")
        _daily_series(graph)

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=_day(10).date(),
            started_before=_day(11).date(),
            limit=20,
            include_scan_completeness=True,
        )

        assert found.status == "available"
        assert 0 < len(found.transcripts) < 20, "a window shorter than the limit that was asked for"
        assert found.scan_incomplete is True, (
            "and yet the collection was not read to its end, so this short list is NOT the whole "
            "window — the claim a caller would otherwise read off its length"
        )
        described = str(lister.MeetingTranscripts.model_fields["transcripts"].description)
        assert "the window holds no more than was read" in described
        assert "these are the whole window." not in described, (
            "the unqualified claim, which this meeting is the counter-example to"
        )

    async def test_the_order_is_promised_over_what_was_read_and_not_over_the_meeting(self) -> None:
        """The sentence the case above makes false if it drifts back. A model reads this field's
        description to decide whether the first entry is "the latest transcript of the series", so
        it has to name the cap and say what the order is over past it."""
        described = str(lister.MeetingTranscripts.model_fields["transcripts"].description)

        assert str(meetings.MAX_ARTIFACT_SCAN) in described
        assert "The order is over every transcript this call read" in described
        assert "not over one page of Microsoft's answer" in described
        assert "The order is over the whole collection" not in described

    async def test_a_limit_above_the_ceiling_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await lister.list_meeting_transcripts(
                client,
                handle=_handle(),
                started_after=None,
                started_before=None,
                limit=lister.MAX_TRANSCRIPTS + 1,
                include_scan_completeness=False,
            )

    async def test_each_transcript_carries_a_handle_and_the_link_to_its_recording(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _resolved(graph)
        graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(200, json={"value": [transcript_payload()]})
        )

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=None,
            started_before=None,
            limit=20,
            include_scan_completeness=False,
        )

        summary = found.transcripts[0]
        assert handles.transcript_handle(summary.uri) == handles.TranscriptHandle(
            MEETING_ID, _TRANSCRIPT_ID
        )
        assert summary.content_correlation_id == "bc842d7a-2f6e-4b18-a1c7-73ef91d5c8e3"
        assert summary.started_at is not None and summary.ended_at is not None


class TestTheWindowShapesAModelActuallySends:
    """A window is the only reason `started_after`/`started_before` exist, and a model writes a date
    the way people write dates. `2026-02-10` and `2026-02-10T14:00:00` both used to reach a
    comparison between a naive datetime and Graph's aware one and raise `TypeError` at the caller —
    a crash naming no remedy, for a value the schema had accepted.

    What the resolution itself does with each shape is `tests/shared/test_meetings.py`'s, since
    `OccurrenceWindow` is a promise about the meeting. What is here is that each shape reaches this
    tool's answer, and bounds this tool's collection, without raising.
    """

    @pytest.mark.parametrize(
        ("started_after", "started_before", "expected"),
        [
            (date(2026, 2, 10), date(2026, 2, 10), ["week-2"]),
            (datetime(2026, 2, 10, 14, 0), datetime(2026, 2, 10, 14, 2), ["week-2"]),
            (datetime(2026, 2, 10), datetime(2026, 2, 11), ["week-2"]),
            (
                datetime(2026, 2, 10, 15, 0, tzinfo=_CET),
                datetime(2026, 2, 10, 16, 0, tzinfo=_CET),
                ["week-2"],
            ),
            (datetime(2026, 2, 10, 14, 0, tzinfo=UTC), None, ["week-3", "week-2"]),
            (None, date(2026, 2, 10), ["week-2", "week-1"]),
        ],
        ids=[
            "bare-dates",
            "naive-datetimes",
            "naive-midnights",
            "offset-aware",
            "open-at-the-top",
            "open-at-the-bottom",
        ],
    )
    async def test_every_shape_bounds_the_series_and_none_of_them_raises(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        started_after: date | datetime | None,
        started_before: date | datetime | None,
        expected: list[str],
    ) -> None:
        """The `_CET` case is the one that has to differ from the naive one: `15:00+01:00` is
        `14:00Z`, so an offset is honoured rather than dropped, and a bound that carries none is not
        silently given the host's."""
        _weekly_series(graph)

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=started_after,
            started_before=started_before,
            limit=20,
            include_scan_completeness=False,
        )

        assert found.status == "available"
        assert [summary.transcript_id for summary in found.transcripts] == expected

    async def test_a_bare_date_keeps_the_last_minute_of_its_day_and_not_the_next_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """What "the whole day" has to mean at the edges, where an off-by-one is invisible: a turn
        transcribed at 23:59 belongs to the day asked for and one at 00:00 does not."""
        _resolved(graph, meeting_type="recurring")
        graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        transcript_payload(transcript_id="dawn", created_at="2026-02-10T00:00:01Z"),
                        transcript_payload(transcript_id="dusk", created_at="2026-02-10T23:59:30Z"),
                        transcript_payload(
                            transcript_id="after", created_at="2026-02-11T00:00:30Z"
                        ),
                    ]
                },
            )
        )

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=date(2026, 2, 10),
            started_before=date(2026, 2, 10),
            limit=20,
            include_scan_completeness=False,
        )

        assert [summary.transcript_id for summary in found.transcripts] == ["dusk", "dawn"]

    async def test_a_graph_timestamp_carrying_no_offset_is_still_comparable(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The other side of the same crash. Graph timestamps in UTC and says so with a `Z`, but a
        window is worth nothing if one payload without one takes the whole call down — so the
        transcript's own timestamp is resolved on the same assumption as the bounds."""
        _resolved(graph, meeting_type="recurring")
        graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        transcript_payload(transcript_id="naive", created_at="2026-02-10T14:01:00")
                    ]
                },
            )
        )

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=date(2026, 2, 10),
            started_before=date(2026, 2, 10),
            limit=20,
            include_scan_completeness=False,
        )

        assert [summary.transcript_id for summary in found.transcripts] == ["naive"]


class TestTheVerdictIsAboutTheWindowThatWasAskedFor:
    """`not_ready` and `not_transcribed` are the same empty collection and opposite advice, so which
    one is given has to follow the window the caller asked about. Reading it off the *meeting* is
    wrong in exactly the case the window exists for: a series is one meeting, its `endDateTime` is
    one value for the whole series, and a caller told to wait for an occurrence that ended last
    month waits forever.
    """

    @pytest.mark.parametrize(
        "end",
        [None, (datetime.now(UTC) + timedelta(days=180)).isoformat()],
        ids=["no-end-time", "series-runs-for-months"],
    )
    async def test_a_long_past_occurrence_of_a_running_series_was_never_transcribed(
        self, client: GraphServiceClient, graph: respx.MockRouter, end: str | None
    ) -> None:
        past = (datetime.now(UTC) - timedelta(days=30)).date()
        _weekly_series(graph, end=end)

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=past,
            started_before=past,
            limit=20,
            include_scan_completeness=False,
        )

        assert found.transcripts == []
        assert found.status == "not_transcribed", (
            "the occurrence is a month gone; the series' own end time says nothing about it"
        )

    async def test_a_window_that_has_only_just_closed_is_still_not_ready(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The allowance has to keep applying to the window itself, or the fix for one wrong answer
        becomes the other one: a transcript minutes away would be reported as never coming."""
        _weekly_series(graph, end=None)

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=datetime.now(UTC) - timedelta(hours=1),
            started_before=datetime.now(UTC) - timedelta(minutes=5),
            limit=20,
            include_scan_completeness=False,
        )

        assert found.status == "not_ready"

    async def test_a_window_still_open_at_its_far_end_admits_the_answer_is_not_known(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Where it genuinely cannot be told, it still says wait. `started_after` alone leaves the
        window running up to now, and a series with no end time offers no second piece of evidence —
        Graph publishes neither a processing status nor an SLA, so the cheap wrong answer wins."""
        _weekly_series(graph, end=None)

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=datetime.now(UTC) - timedelta(days=30),
            started_before=None,
            limit=20,
            include_scan_completeness=False,
        )

        assert found.status == "not_ready"

    async def test_a_meeting_long_over_settles_even_a_window_set_in_the_future(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Either side may settle it. A window a caller put in next week is not an instruction to
        wait for a meeting that ended nine days ago — nothing more is coming from it."""
        _resolved(graph, end=(datetime.now(UTC) - timedelta(days=9)).isoformat())
        graph.get(_TRANSCRIPTS).mock(return_value=httpx.Response(200, json={"value": []}))

        found = await lister.list_meeting_transcripts(
            client,
            handle=_handle(),
            started_after=(datetime.now(UTC) + timedelta(days=7)).date(),
            started_before=None,
            limit=20,
            include_scan_completeness=False,
        )

        assert found.status == "not_transcribed"
