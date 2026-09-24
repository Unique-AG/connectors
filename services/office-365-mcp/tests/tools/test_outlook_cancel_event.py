import json
from collections.abc import Mapping, Sequence
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphNotFound, GraphThrottled, GraphUnavailable
from office_365_mcp.shared.handles import EventHandle
from office_365_mcp.shared.seam import Confirm
from office_365_mcp.tools.outlook_cancel_event import CancelledEvent, cancel_event

_CALENDAR_ID = "AAMkSYNTHETIC-cal-0001="
_EVENT_ID = "AAMkAGI2SYNTHETIC-event-0001="

_EVENT_PATH = f"/me/calendars/{quote(_CALENDAR_ID, safe='')}/events/{quote(_EVENT_ID, safe='')}"
_CANCEL_PATH = f"{_EVENT_PATH}/cancel"

_URI = EventHandle(_CALENDAR_ID, _EVENT_ID).uri

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"


def _attendee(address: str, *, kind: str = "required") -> dict[str, object]:
    return {
        "type": kind,
        "status": {"response": "none", "time": "0001-01-01T00:00:00Z"},
        "emailAddress": {"name": None, "address": address},
    }


def _event(
    *,
    subject: str | None = "Pricing review",
    attendees: Sequence[Mapping[str, object]] = (),
    is_organizer: bool | None = True,
    organizer: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": _EVENT_ID,
        "subject": subject,
        "bodyPreview": "",
        "start": {"dateTime": "2026-03-02T14:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-03-02T15:00:00.0000000", "timeZone": "UTC"},
        "isAllDay": False,
        "isCancelled": False,
        "type": "singleInstance",
        "seriesMasterId": None,
        "sensitivity": "normal",
        "showAs": "busy",
        "location": None,
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


def _cancels(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_CANCEL_PATH).mock(return_value=httpx.Response(202))


def _ready(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    _ = _reads(graph, payload)
    return _cancels(graph)


async def _agrees(question: str, about: str) -> str | None:
    assert question
    assert about
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "Nothing was cancelled."


async def _cancel(
    client: GraphServiceClient,
    *,
    uri: str = _URI,
    comment: str | None = None,
    confirm: Confirm = _agrees,
) -> CancelledEvent:
    answer = await cancel_event(client, uri=uri, comment=comment, confirm=confirm)
    assert isinstance(answer, CancelledEvent), (
        "this call was answered with a question, not a cancel"
    )
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


class TestWhatItSendsToGraph:
    async def test_it_reads_the_event_then_cancels_it_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        cancel = _cancels(graph)

        _ = await _cancel(client)

        assert read.call_count == 1
        assert cancel.call_count == 1
        assert len(graph.calls) == 2

    async def test_the_comment_reaches_graph_verbatim(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[]))
        cancel = _cancels(graph)

        _ = await _cancel(client, comment="Cancelling for this week")

        assert _sent(cancel)["Comment"] == "Cancelling for this week"

    async def test_no_comment_is_omitted_rather_than_sent_as_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[]))
        cancel = _cancels(graph)

        _ = await _cancel(client)

        assert "Comment" not in _sent(cancel)


class TestThePersonBetweenTheRequestAndTheCancellationMail:
    async def test_a_refusal_cancels_nothing_after_the_read_that_precedes_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        cancel = _cancels(graph)

        with pytest.raises(ToolError, match="Nothing was cancelled"):
            _ = await _cancel(client, confirm=_refuses)

        assert read.call_count == 1
        assert cancel.call_count == 0

    async def test_an_event_with_nobody_on_it_is_cancelled_without_asking(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[]))
        cancel = _cancels(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _cancel(client, confirm=counting)

        assert asked == [], "cancelling a private event interrupted the user"
        assert cancel.call_count == 1

    async def test_an_event_with_an_attendee_is_put_to_a_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA), _attendee(_GRACE)]))
        cancel = _cancels(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _cancel(client, confirm=counting)

        assert len(asked) == 1
        assert _ADA in asked[0]
        assert _GRACE in asked[0]
        assert "cannot recall" in asked[0]
        assert cancel.call_count == 1

    async def test_the_question_names_the_subject_and_the_comment(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(subject="Weekly sync", attendees=[_attendee(_ADA)]))
        _ = _cancels(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _cancel(client, comment="No longer needed", confirm=capturing)

        question = asked[0]
        assert "Weekly sync" in question
        assert "No longer needed" in question


class TestWhatItRefuses:
    async def test_a_handle_that_is_not_an_event_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not one"):
            _ = await _cancel(client, uri="outlook:///calendars/x")

        assert len(graph.calls) == 0

    async def test_an_attendee_of_the_meeting_cannot_cancel_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)], is_organizer=False))
        cancel = _cancels(graph)

        with pytest.raises(ToolError, match="not its organizer"):
            _ = await _cancel(client)

        assert cancel.call_count == 0

    async def test_an_unknown_organizer_flag_does_not_refuse_up_front(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[], is_organizer=None))
        cancel = _cancels(graph)

        _ = await _cancel(client)

        assert cancel.call_count == 1


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_cancel_graph_answers_503_is_never_posted_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        cancel = graph.post(_CANCEL_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _cancel(client)

        assert cancel.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_cancel_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        cancel = graph.post(_CANCEL_PATH).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "5"})
        )

        with pytest.raises(GraphThrottled):
            _ = await _cancel(client)

        assert cancel.call_count == 1


class TestGraphErrors:
    async def test_the_event_not_being_found_propagates_as_graph_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_EVENT_PATH).mock(return_value=httpx.Response(404))

        with pytest.raises(GraphNotFound):
            _ = await _cancel(client)


class TestWhatItAnswers:
    async def test_the_answer_is_built_from_the_pre_cancel_read_and_reports_notified_true(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _event(subject="Weekly sync", attendees=[_attendee(_ADA)]))

        answer = await _cancel(client, comment="No longer needed")

        assert answer.uri == _URI
        assert answer.subject == "Weekly sync"
        assert [a.address for a in answer.attendees] == [_ADA]
        assert answer.comment == "No longer needed"
        assert answer.notified is True

    async def test_an_event_with_nobody_on_it_reports_notified_false(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _event(attendees=[]))

        answer = await _cancel(client)

        assert answer.attendees == []
        assert answer.notified is False
