"""Every payload here is synthesised. No event in this file was ever created in a real calendar,
and no address in it resolves anywhere."""

import json
from collections.abc import Mapping, Sequence
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import respx
from fastmcp import Context
from fastmcp.exceptions import ToolError
from mcp.types import ElicitRequest, ElicitRequestFormParams, ElicitResult, InputRequiredResult
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphNotFound, GraphThrottled, GraphUnavailable
from office_365_mcp.shared.calendar import MAX_ATTENDEES, MAX_TIMED_EVENT_HOURS
from office_365_mcp.shared.handles import EventHandle
from office_365_mcp.shared.seam import Confirm
from office_365_mcp.tools.outlook_update_event import UpdatedEvent, a_person_agrees, update_event

_CALENDAR_ID = "AAMkSYNTHETIC-cal-0001="
_EVENT_ID = "AAMkAGI2SYNTHETIC-event-0001="

_EVENT_PATH = f"/me/calendars/{quote(_CALENDAR_ID, safe='')}/events/{quote(_EVENT_ID, safe='')}"

_URI = EventHandle(_CALENDAR_ID, _EVENT_ID).uri

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"
_PAM = "pam@example.invalid"
_ROOM = "room-3@example.invalid"


def _moment(local: str = "2026-03-02T14:00:00.0000000", zone: str = "UTC") -> dict[str, object]:
    return {"dateTime": local, "timeZone": zone}


def _attendee(address: str, *, kind: str = "required") -> dict[str, object]:
    return {
        "type": kind,
        "status": {"response": "none", "time": "0001-01-01T00:00:00Z"},
        "emailAddress": {"name": None, "address": address},
    }


def _event(
    *,
    subject: str | None = "Pricing review",
    start: Mapping[str, object] | None = None,
    end: Mapping[str, object] | None = None,
    location: Mapping[str, object] | None = None,
    attendees: Sequence[Mapping[str, object]] = (),
    is_organizer: bool | None = True,
    organizer: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": _EVENT_ID,
        "subject": subject,
        "bodyPreview": "",
        "start": dict(start) if start is not None else _moment(),
        "end": dict(end) if end is not None else _moment("2026-03-02T15:00:00.0000000"),
        "isAllDay": False,
        "isCancelled": False,
        "type": "singleInstance",
        "seriesMasterId": None,
        "sensitivity": "normal",
        "showAs": "busy",
        "location": dict(location) if location is not None else None,
        "isOnlineMeeting": False,
        "onlineMeeting": None,
        "organizer": (
            dict(organizer)
            if organizer is not None
            else {"emailAddress": {"name": "Ada Lovelace", "address": _ADA}}
        ),
        "isOrganizer": is_organizer,
        "responseStatus": {"response": "organizer", "time": "0001-01-01T00:00:00Z"},
        "attendees": [dict(one) for one in attendees],
        "webLink": "https://outlook.office365.invalid/calendar/item/synthetic-event",
    }


def _reads(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    return graph.get(_EVENT_PATH).mock(
        return_value=httpx.Response(200, json=payload if payload is not None else _event())
    )


def _updates(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    return graph.patch(_EVENT_PATH).mock(
        return_value=httpx.Response(200, json=payload if payload is not None else _event())
    )


def _ready(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    _ = _reads(graph)
    return _updates(graph, payload)


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "Nothing was changed."


async def _update(
    client: GraphServiceClient,
    *,
    uri: str = _URI,
    subject: str | None = None,
    starts_at: str | None = None,
    ends_at: str | None = None,
    time_zone: str | None = None,
    location: str | None = None,
    attendees: Sequence[str] | None = None,
    optional_attendees: Sequence[str] | None = None,
    confirm: Confirm = _agrees,
) -> UpdatedEvent:
    answer = await update_event(
        client,
        uri=uri,
        subject=subject,
        starts_at=starts_at,
        ends_at=ends_at,
        time_zone=time_zone,
        location=location,
        attendees=attendees,
        optional_attendees=optional_attendees,
        confirm=confirm,
    )
    assert isinstance(answer, UpdatedEvent), "this call was answered with a question, not an event"
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _made(route: respx.Route) -> Sequence[Call]:
    return cast("Sequence[Call]", route.calls)


def _object(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value)


class TestWhatItSendsToGraph:
    async def test_it_reads_the_event_then_patches_it_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        patch = _updates(graph)

        _ = await _update(client, subject="Pricing review (rescheduled)")

        assert read.call_count == 1
        assert patch.call_count == 1
        assert len(graph.calls) == 2, "an update costs the read and the patch, and nothing else"

    async def test_a_subject_only_change_sends_only_the_subject(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        _ = await _update(client, subject="Renamed")

        # `Event` always writes its own `@odata.type` discriminator alongside whatever this tool
        # actually asked to change.
        sent = _sent(patch)
        assert sent == {"subject": "Renamed", "@odata.type": "#microsoft.graph.event"}

    async def test_the_time_trio_reaches_graph_together(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        _ = await _update(
            client,
            starts_at="2026-03-02T16:00",
            ends_at="2026-03-02T17:00",
            time_zone="Europe/Zurich",
        )

        sent = _sent(patch)
        assert _object(sent["start"]) == {
            "dateTime": "2026-03-02T16:00",
            "timeZone": "Europe/Zurich",
        }
        assert _object(sent["end"]) == {"dateTime": "2026-03-02T17:00", "timeZone": "Europe/Zurich"}
        assert "subject" not in sent

    async def test_location_alone_is_sent_as_the_only_change(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        _ = await _update(client, location="Room 9")

        sent = _sent(patch)
        assert _object(sent["location"])["displayName"] == "Room 9"
        assert "subject" not in sent
        assert "attendees" not in sent

    async def test_attendees_and_optional_attendees_reach_graph_as_one_merged_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        _ = await _update(client, attendees=[_ADA, _GRACE], optional_attendees=[_PAM])

        sent = _sent(patch)
        invited = [
            (cast("str", cast("Mapping[str, object]", a["emailAddress"])["address"]), a["type"])
            for a in cast("Sequence[Mapping[str, object]]", sent["attendees"])
        ]
        assert invited == [(_ADA, "required"), (_GRACE, "required"), (_PAM, "optional")]

    async def test_clearing_every_attendee_sends_an_explicit_empty_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`[]` and omitting the key are different instructions to Microsoft: only the first one
        clears whoever was already invited."""
        patch = _ready(graph)

        _ = await _update(client, attendees=[], optional_attendees=[])

        sent = _sent(patch)
        assert sent["attendees"] == []

    async def test_a_preexisting_resource_attendee_is_carried_forward_when_attendees_change(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft replaces the WHOLE attendee collection on any attendees update: a room this
        connector never added would be silently un-booked without this."""
        _ = _reads(graph, _event(attendees=[_attendee(_ADA), _attendee(_ROOM, kind="resource")]))
        patch = _updates(graph)

        _ = await _update(client, attendees=[_GRACE], optional_attendees=[])

        sent = _sent(patch)
        invited = [
            (cast("str", cast("Mapping[str, object]", a["emailAddress"])["address"]), a["type"])
            for a in cast("Sequence[Mapping[str, object]]", sent["attendees"])
        ]
        assert invited == [(_GRACE, "required"), (_ROOM, "resource")]

    async def test_a_resource_attendee_is_not_added_when_attendees_are_left_untouched(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ROOM, kind="resource")]))
        patch = _updates(graph)

        _ = await _update(client, subject="Renamed")

        assert "attendees" not in _sent(patch)

    async def test_a_place_with_whitespace_around_it_is_trimmed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        _ = await _update(client, location="  Room 3  ")

        assert _object(_sent(patch)["location"])["displayName"] == "Room 3"

    async def test_a_whitespace_only_location_is_refused_rather_than_read_as_clearing_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        patch = _updates(graph)

        with pytest.raises(ToolError, match="only whitespace"):
            _ = await _update(client, location="   ")

        assert read.call_count == 0
        assert patch.call_count == 0


class TestThePersonBetweenTheRequestAndTheChange:
    async def test_a_refusal_writes_nothing_after_the_read_that_precedes_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        patch = _updates(graph)

        with pytest.raises(ToolError, match="Nothing was changed"):
            _ = await _update(client, attendees=[_ADA], optional_attendees=[], confirm=_refuses)

        assert read.call_count == 1
        assert patch.call_count == 0

    async def test_a_change_that_touches_neither_attendees_nor_location_on_an_event_with_nobody_on_it_is_never_put_to_a_person(  # noqa: E501
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[]))
        patch = _updates(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _update(client, subject="Renamed", confirm=counting)

        assert asked == [], "a subject-only change on a private event interrupted the user"
        assert patch.call_count == 1

    async def test_a_change_on_an_event_that_already_has_attendees_is_put_to_a_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        _ = _updates(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _update(client, subject="Renamed", confirm=counting)

        assert len(asked) == 1
        assert "Renamed" in asked[0]
        assert "cannot recall" in asked[0]

    async def test_a_new_location_on_an_event_with_nobody_on_it_is_still_put_to_a_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[]))
        _ = _updates(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _update(client, location="Room 9", confirm=counting)

        assert len(asked) == 1

    async def test_the_question_names_every_kind_of_change_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        _ = _updates(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _update(
            client,
            subject="Renamed",
            starts_at="2026-03-02T16:00",
            ends_at="2026-03-02T17:00",
            time_zone="UTC",
            location="Room 9",
            attendees=[_GRACE],
            optional_attendees=[],
            confirm=capturing,
        )

        question = asked[0]
        assert "Renamed" in question
        assert "Room 9" in question
        assert _GRACE in question
        assert "cannot recall" in question


class TestTheEraWithNoBackChannel:
    async def test_the_second_round_updates_the_event_under_the_id_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        patch = _updates(graph)

        first = await update_event(
            client,
            uri=_URI,
            subject="Renamed",
            starts_at=None,
            ends_at=None,
            time_zone=None,
            location=None,
            attendees=None,
            optional_attendees=None,
            confirm=a_person_agrees(_modern_context()),
        )
        assert isinstance(first, InputRequiredResult)
        requests = first.input_requests or {}
        key = next(iter(requests))
        request = requests[key]
        assert isinstance(request, ElicitRequest)
        params = request.params
        assert isinstance(params, ElicitRequestFormParams)
        schema = cast(
            "Mapping[str, object]",
            cast("Mapping[str, object]", params.requested_schema)["properties"],
        )
        agree = cast("Sequence[str]", cast("Mapping[str, object]", schema["value"])["enum"])[0]
        assert first.request_state is not None

        second = await update_event(
            client,
            uri=_URI,
            subject="Renamed",
            starts_at=None,
            ends_at=None,
            time_zone=None,
            location=None,
            attendees=None,
            optional_attendees=None,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agree})},
                    state=first.request_state,
                )
            ),
        )
        assert isinstance(second, UpdatedEvent)
        assert patch.call_count == 1


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


def _modern_context(
    *, answers: Mapping[str, object] | None = None, state: str | None = None
) -> Context:
    class _Client:
        request_context: _ModernRequest = _ModernRequest()
        input_responses: Mapping[str, object] | None = answers
        request_state: str | None = state

        async def elicit(self, message: str, response_type: object = None) -> object:
            raise AssertionError(
                f"a connection with no back-channel was asked {message!r} over it, "
                + f"expecting {response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


class TestWhatItRefuses:
    async def test_a_handle_that_is_not_an_event_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not one"):
            _ = await _update(client, uri="outlook:///calendars/x", subject="Renamed")

        assert len(graph.calls) == 0

    async def test_nothing_to_change_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="no argument that changes anything"):
            _ = await _update(client)

        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        ("starts_at", "ends_at", "time_zone"),
        [
            ("2026-03-02T16:00", None, "UTC"),
            (None, "2026-03-02T17:00", "UTC"),
            ("2026-03-02T16:00", "2026-03-02T17:00", None),
        ],
        ids=["starts-only", "ends-only", "zone-only"],
    )
    async def test_a_partial_time_trio_never_reaches_graph(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        starts_at: str | None,
        ends_at: str | None,
        time_zone: str | None,
    ) -> None:
        with pytest.raises(ToolError, match="without the other two"):
            _ = await _update(client, starts_at=starts_at, ends_at=ends_at, time_zone=time_zone)

        assert len(graph.calls) == 0

    async def test_an_end_that_is_not_after_the_start_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not after"):
            _ = await _update(
                client,
                starts_at="2026-03-02T17:00",
                ends_at="2026-03-02T16:00",
                time_zone="UTC",
            )

        assert len(graph.calls) == 0

    async def test_a_span_longer_than_the_ceiling_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match=f"{MAX_TIMED_EVENT_HOURS} hours"):
            _ = await _update(
                client,
                starts_at="2026-03-02T09:00",
                ends_at="2026-03-04T09:00",
                time_zone="UTC",
            )

        assert len(graph.calls) == 0

    async def test_attendees_given_without_optional_attendees_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="without the other"):
            _ = await _update(client, attendees=[_ADA])

        assert len(graph.calls) == 0

    async def test_optional_attendees_given_without_attendees_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="without the other"):
            _ = await _update(client, optional_attendees=[_ADA])

        assert len(graph.calls) == 0

    async def test_a_malformed_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not one"):
            _ = await _update(
                client, attendees=["Ada Lovelace <ada@example.invalid>"], optional_attendees=[]
            )

        assert len(graph.calls) == 0

    async def test_one_person_in_both_lists_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="both"):
            _ = await _update(client, attendees=[_ADA], optional_attendees=[_ADA])

        assert len(graph.calls) == 0

    async def test_more_addresses_than_the_ceiling_never_reach_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        too_many = [f"guest{index}@example.invalid" for index in range(MAX_ATTENDEES + 1)]

        with pytest.raises(ToolError, match="between them"):
            _ = await _update(client, attendees=too_many, optional_attendees=[])

        assert len(graph.calls) == 0


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_patch_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        patch = graph.patch(_EVENT_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _update(client, subject="Renamed")

        assert patch.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_patch_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        patch = graph.patch(_EVENT_PATH).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "5"})
        )

        with pytest.raises(GraphThrottled):
            _ = await _update(client, subject="Renamed")

        assert patch.call_count == 1


class TestGraphErrors:
    async def test_the_event_not_being_found_propagates_as_graph_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_EVENT_PATH).mock(return_value=httpx.Response(404))

        with pytest.raises(GraphNotFound):
            _ = await _update(client, subject="Renamed")


class TestWhatItAnswers:
    async def test_the_answer_reports_the_updated_attendees_from_the_response(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[]))
        _ = _updates(graph, _event(attendees=[_attendee(_GRACE)]))

        answer = await _update(client, attendees=[_GRACE], optional_attendees=[])

        assert [a.address for a in answer.attendees] == [_GRACE]
        assert answer.uri == _URI
