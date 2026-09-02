"""`teams_list_meeting_recordings`: what exists, how long it ran, and who may download it."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import cast

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared import handles, meetings
from office_365_mcp.tools import teams_list_meeting_recordings as lister

from .conftest import (
    GRAPH_V1,
    JOIN_WEB_URL,
    ME,
    MEETING_ID,
    OTHER_USER_ID,
    SIGNED_IN_USER_ID,
    meeting_payload,
    recording_payload,
)

_MEETINGS = "/me/onlineMeetings"
_RECORDINGS = f"/me/onlineMeetings/{MEETING_ID}/recordings"
_RECORDING_ID = "7e31db25-bc6e-4fd8-96c7-e01264e9b6fc"
_CONTENT = f"{_RECORDINGS}/{_RECORDING_ID}/content"


def _handle() -> handles.MeetingHandle:
    handle = handles.meeting_handle(handles.meeting_uri_for(JOIN_WEB_URL) or "")
    assert handle is not None
    return handle


def _me(graph: respx.MockRouter) -> respx.Route:
    return graph.get("/me").mock(return_value=httpx.Response(200, json=ME))


def _resolved(graph: respx.MockRouter, **meeting: object) -> respx.Route:
    return graph.get(_MEETINGS).mock(
        return_value=httpx.Response(200, json={"value": [meeting_payload(**meeting)]})  # pyright: ignore[reportArgumentType]
    )


def _listed(graph: respx.MockRouter, *payloads: object) -> respx.Route:
    return graph.get(_RECORDINGS).mock(
        return_value=httpx.Response(200, json={"value": list(payloads)})
    )


def _published(*path: str) -> Mapping[str, object]:
    """A named subschema of this tool's output, narrowed off pydantic's `dict[str, Any]`."""
    found: Mapping[str, object] = lister.MeetingRecordings.model_json_schema()
    for key in path:
        step = found.get(key)
        assert isinstance(step, dict), f"expected an object at {key!r}, got {step!r}"
        found = cast("Mapping[str, object]", step)
    return found


def _pages(
    graph: respx.MockRouter, first: list[dict[str, object]], second: list[dict[str, object]]
) -> respx.Route:
    """Two real pages rather than one linking to itself, because the walk follows the cursor to
    the end of the collection (bounded by `MAX_ARTIFACT_SCAN`) rather than stopping at `limit`."""
    return graph.get(_RECORDINGS).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "value": first,
                    "@odata.nextLink": f"{GRAPH_V1}{_RECORDINGS}?$skiptoken=synthetic",
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
    return _listed(
        graph,
        *(
            recording_payload(
                recording_id=f"day-{index}",
                created_at=_day(index).isoformat().replace("+00:00", "Z"),
            )
            for index in range(total)
        ),
    )


def _weekly_series(graph: respx.MockRouter, *, end: str | None = "2026-02-17T15:00:00Z") -> None:
    """Three occurrences in one collection, because Graph publishes no occurrence id and no
    per-occurrence addressing."""
    _resolved(graph, meeting_type="recurring", end=end)
    _listed(
        graph,
        recording_payload(recording_id="week-1", created_at="2026-02-03T14:02:00Z"),
        recording_payload(recording_id="week-2", created_at="2026-02-10T14:01:00Z"),
        recording_payload(recording_id="week-3", created_at="2026-02-17T14:04:00Z"),
    )


async def _listing(
    client: GraphServiceClient,
    *,
    started_after: date | datetime | None = None,
    started_before: date | datetime | None = None,
    limit: int = 20,
    include_scan_completeness: bool = False,
) -> lister.MeetingRecordings:
    return await lister.teams_list_meeting_recordings(
        client,
        handle=_handle(),
        started_after=started_after,
        started_before=started_before,
        limit=limit,
        include_scan_completeness=include_scan_completeness,
    )


class TestWhatOneRecordingIsReportedAs:
    async def test_it_answers_existence_duration_and_reachability(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The duration is derived, because Microsoft publishes no duration, size or media-type
        property on `callRecording`. The correlation id is Microsoft's own link to the transcript
        of the same call."""
        _resolved(graph)
        listing = _listed(graph, recording_payload())
        _me(graph)

        found = await _listing(client)

        assert found.status == "available"
        assert found.meeting_id == MEETING_ID
        assert found.subject == "Pricing review"
        assert found.scan_incomplete is None, "nobody asked how far the read got"
        assert listing.called
        recording = found.recordings[0]
        assert recording.recording_id == _RECORDING_ID
        assert recording.duration_seconds == pytest.approx(2831.913)
        assert recording.content_correlation_id == "bc842d7a-2f6e-4b18-a1c7-73ef91d5c8e3"
        assert recording.started_at is not None and recording.ended_at is not None

    async def test_nothing_fetches_the_video(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A recording is an MP4 of a meeting that can run 30 hours."""
        _resolved(graph)
        _listed(graph, recording_payload())
        _me(graph)
        content = graph.get(_CONTENT).mock(return_value=httpx.Response(200, content=b"not an mp4"))

        found = await _listing(client)

        assert found.status == "available"
        assert not content.called

    def test_a_recording_carries_no_handle_because_nothing_reads_one(self) -> None:
        assert "uri" not in lister.RecordingSummary.model_fields


class TestTheOrganiserOnlyConstraint:
    """Microsoft: recording content is "supported only for the meeting organizer", unless a tenant
    administrator unblocked participants. The metadata is not so restricted, so the two are
    reported separately and an unreachable recording must never read as a missing one."""

    @pytest.mark.parametrize(
        ("organizer", "expected"),
        [
            (OTHER_USER_ID, "organizer_only"),
            (SIGNED_IN_USER_ID, "you_are_the_organizer"),
            (SIGNED_IN_USER_ID.upper(), "you_are_the_organizer"),
            (None, "unknown"),
        ],
        ids=["participant", "organiser", "organiser-in-other-case", "nobody-named"],
    )
    async def test_which_side_of_it_the_signed_in_user_is_on(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        organizer: str | None,
        expected: str,
    ) -> None:
        """An Entra object id is a GUID and its casing is not part of its identity."""
        _resolved(graph)
        _listed(graph, recording_payload(organizer_user_id=organizer))
        _me(graph)

        found = await _listing(client)

        assert found.recordings[0].content_access == expected
        assert found.recordings[0].organizer_user_id == organizer

    async def test_a_recording_it_cannot_download_is_still_listed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _resolved(graph)
        _listed(graph, recording_payload(organizer_user_id=OTHER_USER_ID))
        _me(graph)

        found = await _listing(client)

        assert found.status == "available", "unreachable content is not a missing recording"
        assert found.recordings[0].content_access == "organizer_only"
        assert found.recordings[0].organizer_user_id == OTHER_USER_ID
        assert found.recordings[0].duration_seconds is not None

    async def test_the_organiser_type_microsofts_own_sample_sends_still_deserializes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph's list-recordings sample types the organiser
        `#Microsoft.Teams.GraphSvc.teamworkUserIdentity`, a discriminator the SDK does not know.
        An unknown one falls back to the base identity, which still carries the id."""
        _resolved(graph)
        _listed(
            graph,
            recording_payload(
                organizer_user_id=SIGNED_IN_USER_ID,
                organizer_odata_type="#Microsoft.Teams.GraphSvc.teamworkUserIdentity",
            ),
        )
        _me(graph)

        found = await _listing(client)

        assert found.recordings[0].content_access == "you_are_the_organizer"

    def test_the_three_sides_reach_the_schema_as_an_enum_and_not_only_as_prose(self) -> None:
        """The constraint is Microsoft's but these three words are not — so the field publishes
        them, rather than leaving a model to find them in the description of a `string`."""
        access = _published("$defs", "RecordingSummary", "properties", "content_access")

        assert access["enum"] == ["you_are_the_organizer", "organizer_only", "unknown"]
        assert access["type"] == "string"
        assert "$ref" not in access
        assert "This is NOT a missing recording" in str(access["description"]), (
            "the enum names the three; only the prose says an unreachable one still exists"
        )

    async def test_the_caller_is_not_looked_up_when_there_is_nothing_to_say_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _resolved(graph, end="2026-02-10T15:00:00Z")
        _listed(graph)
        me = _me(graph)

        found = await _listing(client)

        assert found.recordings == []
        assert not me.called


class TestTheDurationIsDerivedOrAbsent:
    @pytest.mark.parametrize(
        ("created_at", "ended_at"),
        [
            (None, "2026-02-10T14:49:53Z"),
            ("2026-02-10T14:02:41Z", None),
            ("2026-02-10T14:49:53Z", "2026-02-10T14:02:41Z"),
        ],
        ids=["no-start", "no-end", "ends-before-it-began"],
    )
    async def test_what_cannot_be_computed_is_null_and_never_invented(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        created_at: str | None,
        ended_at: str | None,
    ) -> None:
        """A negative span is not a duration either, so it is unknown rather than a negative
        number of seconds shown to a caller as a length."""
        _resolved(graph)
        _listed(graph, recording_payload(created_at=created_at, ended_at=ended_at))
        _me(graph)

        found = await _listing(client)

        assert found.recordings[0].duration_seconds is None

    async def test_timestamps_without_an_offset_are_still_subtractable(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph timestamps in UTC and says so with a `Z`, but a payload without one must not take
        the call down through a naive-versus-aware subtraction."""
        _resolved(graph)
        _listed(
            graph,
            recording_payload(created_at="2026-02-10T14:00:00", ended_at="2026-02-10T14:47:11Z"),
        )
        _me(graph)

        found = await _listing(client)

        assert found.recordings[0].duration_seconds == pytest.approx(2831.0)


class TestTheKindsOfAbsence:
    async def test_no_matching_meeting_is_a_status_and_costs_no_listing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph answers the join-URL filter with `200 OK` and an empty `value`, never a 404."""
        graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))
        listing = _listed(graph, recording_payload())
        me = _me(graph)

        found = await _listing(client)

        assert found.status == "meeting_not_found"
        assert found.meeting_id is None
        assert found.recordings == []
        assert not listing.called and not me.called

    async def test_a_meeting_long_over_with_nothing_in_it_was_not_recorded(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _resolved(graph, end=(datetime.now(UTC) - timedelta(days=9)).isoformat())
        _listed(graph)

        found = await _listing(client)

        assert found.status == "not_recorded"
        assert found.meeting_id == MEETING_ID, "the meeting resolved; nobody recorded it"

    @pytest.mark.parametrize(
        "ended",
        [
            datetime.now(UTC) - timedelta(minutes=5),
            datetime.now(UTC) + timedelta(hours=1),
            None,
        ],
        ids=["just-ended", "still-running", "no-end-time"],
    )
    async def test_a_meeting_that_just_ended_is_not_ready_rather_than_never_recorded(
        self, client: GraphServiceClient, graph: respx.MockRouter, ended: datetime | None
    ) -> None:
        """Microsoft publishes no processing status and no availability SLA for a recording
        either, so the bias is towards the wrong answer that costs a caller one more call."""
        _resolved(graph, end=ended.isoformat() if ended is not None else None)
        _listed(graph)

        found = await _listing(client)

        assert found.status == "not_ready"

    async def test_a_long_past_occurrence_of_a_running_series_was_not_recorded(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A series' own end time says nothing about an occurrence that ended a month ago."""
        past = (datetime.now(UTC) - timedelta(days=30)).date()
        _weekly_series(graph, end=(datetime.now(UTC) + timedelta(days=180)).isoformat())

        found = await _listing(client, started_after=past, started_before=past)

        assert found.recordings == []
        assert found.status == "not_recorded"

    async def test_a_404_is_still_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_MEETINGS).mock(
            return_value=httpx.Response(404, json={"error": {"code": "NotFound", "message": "no"}})
        )

        with pytest.raises(GraphNotFound):
            _ = await _listing(client)

    def test_the_five_answers_reach_the_schema_as_an_enum_and_not_only_as_prose(self) -> None:
        """These five words are this connector's invention, not Microsoft's, so a model can only
        learn them from what this tool publishes. Typed `str` they would arrive as
        `{"type": "string"}` and exist only inside the description. Asserted inline on the property
        rather than anywhere in the document: a `$ref` into `$defs` — what a PEP 695 `type` alias
        would produce — puts them one hop from where the value is read."""
        status = _published("properties", "status")

        assert status["enum"] == [
            "available",
            "not_ready",
            "not_recorded",
            "scan_incomplete",
            "meeting_not_found",
        ]
        assert status["type"] == "string"
        assert "$ref" not in status
        assert "Retrying will not help" in str(status["description"]), (
            "the enum says what the values are; the prose still has to say what to do with them"
        )


class TestScopingToOneOccurrence:
    async def test_the_shared_window_picks_one_occurrence_out_of_the_series(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The window is the transcript lister's own `OccurrenceWindow` from `shared/meetings.py`:
        a series bracketed one way for transcripts and another for recordings would pair the wrong
        occurrence with the wrong call."""
        _weekly_series(graph)
        _me(graph)

        found = await _listing(
            client,
            started_after=datetime(2026, 2, 10, tzinfo=UTC),
            started_before=datetime(2026, 2, 11, tzinfo=UTC),
        )

        assert found.meeting_type == "recurring"
        assert [item.recording_id for item in found.recordings] == ["week-2"]

    @pytest.mark.parametrize(
        ("started_after", "started_before", "expected"),
        [
            (date(2026, 2, 10), date(2026, 2, 10), ["week-2"]),
            (datetime(2026, 2, 10, 14, 0), datetime(2026, 2, 10, 14, 2), ["week-2"]),
            (datetime(2026, 2, 10, 14, 0, tzinfo=UTC), None, ["week-3", "week-2"]),
            (None, date(2026, 2, 10), ["week-2", "week-1"]),
        ],
        ids=["bare-dates", "no-offset", "open-at-the-top", "open-at-the-bottom"],
    )
    async def test_every_window_shape_a_model_writes_is_answered(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        started_after: date | datetime | None,
        started_before: date | datetime | None,
        expected: list[str],
    ) -> None:
        _weekly_series(graph)
        _me(graph)

        found = await _listing(client, started_after=started_after, started_before=started_before)

        assert found.status == "available"
        assert [item.recording_id for item in found.recordings] == expected

    async def test_recordings_come_back_newest_first(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph documents no `$orderby` here either, so its order is not a contract."""
        _resolved(graph)
        _listed(
            graph,
            recording_payload(recording_id="older", created_at="2026-02-03T14:00:00Z"),
            recording_payload(recording_id="newer", created_at="2026-02-17T14:00:00Z"),
        )
        _me(graph)

        found = await _listing(client)

        assert [item.recording_id for item in found.recordings] == ["newer", "older"]

    async def test_a_window_holding_more_than_the_limit_is_a_full_window_and_a_complete_scan(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The two facts one flag would run together: a window filled to `limit` means older ones
        may exist, and the collection was still read to its end."""
        _resolved(graph)
        _pages(
            graph,
            [recording_payload(recording_id="week-1", created_at="2026-02-03T14:00:00Z")],
            [recording_payload(recording_id="week-2", created_at="2026-02-10T14:00:00Z")],
        )
        _me(graph)

        found = await _listing(client, limit=1, include_scan_completeness=True)

        assert found.status == "available"
        assert [item.recording_id for item in found.recordings] == ["week-2"]
        assert len(found.recordings) == 1, "a window filled to `limit`: there may be older ones"
        assert found.scan_incomplete is False, "and no cap was reached, so nothing suggests one was"

    async def test_the_newest_are_returned_and_not_the_first_graph_answered_with(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The collection is ordered before `limit` cuts it. Cutting first would have answered
        `oldest` here."""
        _resolved(graph, meeting_type="recurring")
        _listed(
            graph,
            recording_payload(recording_id="oldest", created_at="2026-02-03T14:00:00Z"),
            recording_payload(recording_id="middle", created_at="2026-02-10T14:00:00Z"),
            recording_payload(recording_id="newest", created_at="2026-02-17T14:00:00Z"),
        )
        _me(graph)

        found = await _listing(client, limit=1)

        assert [item.recording_id for item in found.recordings] == ["newest"]

    async def test_the_newest_is_found_even_when_it_is_on_a_later_page(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _resolved(graph, meeting_type="recurring")
        _pages(
            graph,
            [recording_payload(recording_id="oldest", created_at="2026-02-03T14:00:00Z")],
            [recording_payload(recording_id="newest", created_at="2026-02-17T14:00:00Z")],
        )
        _me(graph)

        found = await _listing(client, limit=1)

        assert [item.recording_id for item in found.recordings] == ["newest"]

    async def test_a_scan_that_stopped_short_asserts_no_absence(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`not_recorded` ("retrying will not help") alongside "there is more" cannot both be
        true, so `scan_incomplete` claims nothing about absence and reaches `status` whether or not
        the caller asked about the scan."""
        ended = datetime.now(UTC) - timedelta(days=30)
        _resolved(graph, meeting_type="recurring", end=ended.isoformat())
        _listed(
            graph,
            *(
                recording_payload(
                    recording_id=f"occurrence-{index}", created_at="2026-02-03T14:00:00Z"
                )
                for index in range(meetings.MAX_ARTIFACT_SCAN + 50)
            ),
        )
        _me(graph)

        found = await _listing(
            client,
            started_after=datetime(2026, 3, 1, tzinfo=UTC),
            started_before=datetime(2026, 3, 2, tzinfo=UTC),
        )

        assert found.recordings == []
        assert found.status == "scan_incomplete"
        assert found.scan_incomplete is None, "and still only `status` says it, unless asked"
        assert found.status not in ("not_recorded", "not_ready"), (
            "a window whose collection was not read to the end settles nothing either way"
        )

    async def test_narrowing_the_window_cannot_reach_past_the_scan_cap(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph documents `contentCorrelationId` as this collection's one filterable property and
        never a date, so the request goes out bare and a narrower window reads the same recordings.
        The narrow window here brackets `day-250`, which genuinely exists and is never seen."""
        _resolved(graph, meeting_type="recurring")
        listing = _daily_series(graph)
        _me(graph)

        wide = await _listing(
            client,
            started_after=_day(meetings.MAX_ARTIFACT_SCAN).date(),
            started_before=_day(_PAST_THE_CAP - 1).date(),
        )
        wide_request = listing.calls.last.request.url
        narrow = await _listing(
            client, started_after=_day(250).date(), started_before=_day(250).date()
        )
        narrow_request = listing.calls.last.request.url

        assert (wide.status, wide.recordings) == ("scan_incomplete", [])
        assert (narrow.status, narrow.recordings) == (wide.status, [])
        assert str(wide_request) == str(narrow_request), "two windows, one request"
        for asked in (wide_request, narrow_request):
            assert not {"$filter", "$orderby", "$top"} & set(asked.params), (
                f"the window is applied here, not by Graph: {asked}"
            )

    async def test_the_unreadable_answer_tells_a_caller_to_stop_rather_than_to_retry(self) -> None:
        described = str(lister.MeetingRecordings.model_fields["status"].description)

        assert "There is nothing to try" in described
        assert "Stop, and report" in described
        assert "returns this same status" in described
        assert "Narrow `started_after`/`started_before` to the occurrence you mean" not in described

    async def test_past_the_cap_the_newest_returned_is_the_newest_of_what_was_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The read stops at `MAX_ARTIFACT_SCAN`, and no `$orderby` exists to ask Graph for the
        newest ahead of it."""
        _resolved(graph, meeting_type="recurring")
        _daily_series(graph)
        _me(graph)

        found = await _listing(client, limit=3, include_scan_completeness=True)

        assert found.status == "available"
        assert found.scan_incomplete is True, "the cap was reached, and the answer has to say so"
        returned = [item.recording_id for item in found.recordings]
        assert returned == ["day-199", "day-198", "day-197"], "the newest of the ones read"
        assert f"day-{_PAST_THE_CAP - 1}" not in returned, (
            "the meeting's genuinely newest recording was never read, which is the whole point"
        )

    async def test_a_short_list_is_not_a_complete_window_when_the_scan_stopped_short(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """ "Fewer than `limit` means the whole window" holds wherever a walk reaches the end of its
        collection, and this walk stops at `MAX_ARTIFACT_SCAN` instead, so a short list can mean the
        opposite of what the convention says."""
        _resolved(graph, meeting_type="recurring")
        _daily_series(graph)
        _me(graph)

        found = await _listing(
            client,
            started_after=_day(10).date(),
            started_before=_day(11).date(),
            limit=20,
            include_scan_completeness=True,
        )

        assert found.status == "available"
        assert 0 < len(found.recordings) < 20, "a window shorter than the limit that was asked for"
        assert found.scan_incomplete is True, (
            "and yet the collection was not read to its end, so this short list is NOT the whole "
            "window — the claim a caller would otherwise read off its length"
        )
        described = str(lister.MeetingRecordings.model_fields["recordings"].description)
        assert "the window holds no more than was read" in described
        assert "these are the whole window." not in described, (
            "the unqualified claim, which this meeting is the counter-example to"
        )

    async def test_the_order_is_promised_over_what_was_read_and_not_over_the_meeting(self) -> None:
        described = str(lister.MeetingRecordings.model_fields["recordings"].description)

        assert str(meetings.MAX_ARTIFACT_SCAN) in described
        assert "the latest of what was READ" in described
        assert "The order is over the whole collection" not in described

    async def test_a_limit_above_the_ceiling_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await _listing(client, limit=lister.MAX_RECORDINGS + 1)


class TestWhatGraphRefusalsLookLikeHere:
    async def test_a_refused_listing_reaches_the_tool_layer_as_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Recordings need their own admin-consented permission, and a tenant may grant transcript
        access without it."""
        _resolved(graph)
        graph.get(_RECORDINGS).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden) as raised:
            _ = await _listing(client)

        assert raised.value.inner_code is None, "an ordinary refusal carries no inner code"


class TestTheRepeatsGraphIsDocumentedToSend:
    """Microsoft's known-issues page (Teamwork and communications) documents an automatic
    pagination token reset on `getAllRecordings` and `getAllTranscripts`: an empty collection with
    an `@odata.nextLink`, after which paging restarts and repeats items already returned. The
    published remedy is to keep following the link and de-duplicate by `id`.

    `graph_client/pagination.py` does the following; `shared/meetings.py` does the de-duplicating,
    which is what these test.
    """

    async def test_a_recording_graph_sent_twice_is_reported_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _me(graph)
        _resolved(graph)
        _pages(
            graph,
            [
                recording_payload(recording_id="a", created_at="2026-02-03T14:00:00Z"),
                recording_payload(recording_id="b", created_at="2026-02-04T14:00:00Z"),
            ],
            # The reset: page two starts the collection again and repeats what page one held.
            [
                recording_payload(recording_id="a", created_at="2026-02-03T14:00:00Z"),
                recording_payload(recording_id="c", created_at="2026-02-05T14:00:00Z"),
            ],
        )

        found = await _listing(client)

        assert [recording.recording_id for recording in found.recordings] == ["c", "b", "a"], (
            "one entry per id, still newest first"
        )

    async def test_a_repeat_does_not_take_the_place_of_an_artifact_the_caller_asked_for(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A repeat surviving into the sort takes one of the `limit` places a distinct recording
        was owed, so the de-duplication happens before the cut and not after it."""
        _me(graph)
        _resolved(graph)
        _pages(
            graph,
            [recording_payload(recording_id="newest", created_at="2026-02-05T14:00:00Z")],
            [
                recording_payload(recording_id="newest", created_at="2026-02-05T14:00:00Z"),
                recording_payload(recording_id="older", created_at="2026-02-04T14:00:00Z"),
            ],
        )

        found = await _listing(client, limit=2)

        assert [recording.recording_id for recording in found.recordings] == ["newest", "older"]
