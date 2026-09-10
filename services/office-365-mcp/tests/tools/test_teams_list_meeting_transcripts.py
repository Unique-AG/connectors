"""`teams_list_meeting_transcripts`: the window, the order, and the five answers."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared import handles, meetings
from office_365_mcp.tools import teams_list_meeting_transcripts as lister

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

# February is in CET, so a European caller's "15:00" is one hour from the UTC the same string
# without an offset is read as.
_CET = timezone(timedelta(hours=1))


def _handle() -> handles.MeetingHandle:
    handle = handles.meeting_handle(handles.meeting_uri_for(JOIN_WEB_URL) or "")
    assert handle is not None
    return handle


def _resolved(graph: respx.MockRouter, **meeting: object) -> respx.Route:
    return graph.get(_MEETINGS).mock(
        return_value=httpx.Response(200, json={"value": [meeting_payload(**meeting)]})  # pyright: ignore[reportArgumentType]
    )


def _published(*path: str) -> Mapping[str, object]:
    """A named subschema of this tool's output, narrowed off pydantic's `dict[str, Any]`."""
    found: Mapping[str, object] = lister.MeetingTranscripts.model_json_schema()
    for key in path:
        step = found.get(key)
        assert isinstance(step, dict), f"expected an object at {key!r}, got {step!r}"
        found = cast("Mapping[str, object]", step)
    return found


def _pages(
    graph: respx.MockRouter, first: list[dict[str, object]], second: list[dict[str, object]]
) -> respx.Route:
    """Two real pages rather than one linking to itself, because the walk follows the cursor to the
    end of the collection (bounded by `shared/meetings.py`'s `MAX_ARTIFACT_SCAN`) rather than
    stopping at `limit`."""
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


# One occurrence a day for the better part of a year, which is the only shape that outgrows
# `MAX_ARTIFACT_SCAN`. Oldest-first is the order that puts the genuinely newest one past the cap.
_DAILY_SERIES_START = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
_PAST_THE_CAP = meetings.MAX_ARTIFACT_SCAN + 60


def _day(index: int) -> datetime:
    return _DAILY_SERIES_START + timedelta(days=index)


def _daily_series(graph: respx.MockRouter, *, total: int = _PAST_THE_CAP) -> respx.Route:
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
    """Three occurrences in one collection, because Graph publishes no occurrence id and no
    per-occurrence addressing. `end` is the series-wide `endDateTime`, which the verdict must NOT
    be read off when a window was asked for."""
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
        """Graph documents this filter as answering `200 OK` with an empty `value`, never a 404."""
        graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))
        listing = graph.get(_TRANSCRIPTS).mock(
            return_value=httpx.Response(200, json={"value": [transcript_payload()]})
        )

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
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
        graph.get(_MEETINGS).mock(
            return_value=httpx.Response(404, json={"error": {"code": "NotFound", "message": "no"}})
        )

        with pytest.raises(GraphNotFound):
            _ = await lister.teams_list_meeting_transcripts(
                client,
                handle=_handle(),
                limit=20,
                include_scan_completeness=False,
            )


class TestTheKindsOfAbsence:
    """Nothing came back — and each reason a model must act on differently has its own status."""

    async def test_the_tenant_switch_is_a_refusal_and_not_an_empty_answer(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`EnableGraphTranscriptAccess` is off, which no permission and no argument works around.
        The inner code is the only thing distinguishing it from an ordinary 403."""
        _resolved(graph)
        graph.get(_TRANSCRIPTS).mock(return_value=httpx.Response(403, json=_TENANT_SWITCH_OFF))

        with pytest.raises(GraphForbidden) as raised:
            _ = await lister.teams_list_meeting_transcripts(
                client,
                handle=_handle(),
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

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
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
        """These two empty answers are the same bytes from Graph and the opposite advice, and a
        meeting Graph gave no end time for counts as "wait"."""
        _resolved(graph, end=ended.isoformat() if ended is not None else None)
        graph.get(_TRANSCRIPTS).mock(return_value=httpx.Response(200, json={"value": []}))

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
            limit=20,
            include_scan_completeness=False,
        )

        assert found.status == "not_ready"

    def test_the_four_answers_reach_the_schema_as_an_enum_and_not_only_as_prose(self) -> None:
        """These four words are this connector's invention, not Microsoft's, so a model can only
        learn them from what this tool publishes. Typed `str` they would arrive as
        `{"type": "string"}` and exist only inside the description. Asserted inline on the property
        rather than anywhere in the document: a `$ref` into `$defs` — what a PEP 695 `type` alias
        would produce — puts them one hop from where the value is read."""
        status = _published("properties", "status")

        assert status["enum"] == [
            "available",
            "not_ready",
            "not_transcribed",
            "meeting_not_found",
        ]
        assert status["type"] == "string"
        assert "$ref" not in status
        assert "Retrying will not change this" in str(status["description"]), (
            "the enum says what the values are; the prose still has to say what to do with them"
        )


class TestScopingToOneOccurrence:
    async def test_transcripts_come_back_newest_first(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph documents no `$orderby` here, so the order it answers in is not a contract."""
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

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
            limit=20,
            include_scan_completeness=False,
        )

        assert [t.transcript_id for t in found.transcripts] == ["newer", "older"]

    async def test_a_window_holding_more_than_the_limit_is_a_full_window_and_a_complete_scan(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The two facts one flag would conflate: a window filled to `limit` means older ones may
        exist, and the collection was still read to its end, so the first entry is the meeting's
        own latest."""
        _resolved(graph)
        _pages(
            graph,
            [transcript_payload(transcript_id="week-1", created_at="2026-02-03T14:00:00Z")],
            [transcript_payload(transcript_id="week-2", created_at="2026-02-10T14:00:00Z")],
        )

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
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
        """Cutting to `limit` before sorting returns an arbitrary handful sorted among themselves,
        which reads exactly like the right answer: here it would have answered `oldest`."""
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

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
            limit=1,
            include_scan_completeness=False,
        )

        assert [t.transcript_id for t in found.transcripts] == ["newest"]

    async def test_the_newest_is_found_even_when_it_is_on_a_later_page(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A walk stopping as soon as it had `limit` items would never have seen the newest."""
        _resolved(graph, meeting_type="recurring")
        _pages(
            graph,
            [transcript_payload(transcript_id="oldest", created_at="2026-02-03T14:00:00Z")],
            [transcript_payload(transcript_id="newest", created_at="2026-02-17T14:00:00Z")],
        )

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
            limit=1,
            include_scan_completeness=False,
        )

        assert [t.transcript_id for t in found.transcripts] == ["newest"]

    async def test_a_capped_scan_never_reports_an_absence(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`not_transcribed` ("retrying will not help") alongside "there is more" cannot both be
        true. Nothing has to reconcile them: with no window to filter rows out, a scan that stops
        at the cap has collected the cap's worth of rows, so it always answers `available`. This is
        why there is no partial-scan status."""
        ended = datetime.now(UTC) - timedelta(days=30)
        _resolved(graph, meeting_type="recurring", end=ended.isoformat())
        _daily_series(graph)

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
            limit=20,
            include_scan_completeness=True,
        )

        assert found.scan_incomplete is True, "the read stopped at the cap"
        assert found.status == "available", (
            "and the rows it stopped on are the answer, so no absence is claimed over a prefix"
        )
        assert len(found.transcripts) == 20, "a capped scan is never short of the asked-for limit"

    async def test_past_the_cap_the_newest_returned_is_the_newest_of_what_was_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Asking for 3 gives the 3 newest of the `MAX_ARTIFACT_SCAN` that were read, not of the
        meeting. Three entries for a `limit` of three is what an ordinary full window looks like
        too, so `scan_incomplete` is the one thing a caller cannot work out from the answer."""
        _resolved(graph, meeting_type="recurring")
        _daily_series(graph)

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
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
        _resolved(graph, meeting_type="recurring")
        _daily_series(graph)

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
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
        """The SDK's own page walker reads the empty middle page here as the end of the
        collection, which would stop one page short of the newest transcript and report a cap it
        never reached on a four-transcript meeting. `graph_client/pagination.py` follows an empty
        page carrying a next link instead."""
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

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
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

    async def test_a_short_list_means_the_collection_was_read_to_its_end(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """ "Fewer than `limit` means there are no more" is trustworthy here only because the
        largest `limit` a caller may ask for sits below the scan cap. A read that stops at the cap
        therefore always has more rows in hand than it was asked for, and can never hand back a
        short list that a caller would misread as the end of the collection."""
        assert lister.MAX_TRANSCRIPTS < meetings.MAX_ARTIFACT_SCAN, (
            "the ceiling that makes a short list mean what the field says it means"
        )
        _resolved(graph, meeting_type="recurring")
        _daily_series(graph)

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
            limit=lister.MAX_TRANSCRIPTS,
            include_scan_completeness=True,
        )

        assert found.scan_incomplete is True, "the collection was not read to its end"
        assert len(found.transcripts) == lister.MAX_TRANSCRIPTS, (
            "and even the largest limit is answered in full, so nothing here reads as an end"
        )
        described = str(lister.MeetingTranscripts.model_fields["transcripts"].description)
        assert "Fewer means it holds no more than was read." in described

    async def test_the_order_is_promised_over_what_was_read_and_not_over_the_meeting(self) -> None:
        described = str(lister.MeetingTranscripts.model_fields["transcripts"].description)

        assert str(meetings.MAX_ARTIFACT_SCAN) in described
        assert "The order is over every transcript this call read" in described
        assert "not over one page of Microsoft's answer" in described
        assert "The order is over the whole collection" not in described

    async def test_a_limit_above_the_ceiling_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await lister.teams_list_meeting_transcripts(
                client,
                handle=_handle(),
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

        found = await lister.teams_list_meeting_transcripts(
            client,
            handle=_handle(),
            limit=20,
            include_scan_completeness=False,
        )

        summary = found.transcripts[0]
        assert handles.transcript_handle(summary.uri) == handles.TranscriptHandle(
            MEETING_ID, _TRANSCRIPT_ID
        )
        assert summary.content_correlation_id == "bc842d7a-2f6e-4b18-a1c7-73ef91d5c8e3"
        assert summary.started_at is not None and summary.ended_at is not None
