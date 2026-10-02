import json
from collections.abc import Mapping, Sequence
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphNotFound, GraphThrottled, GraphUnavailable
from office_365_mcp.shared.calendar import SERIES_MASTER_FIELD
from office_365_mcp.shared.handles import EventHandle
from office_365_mcp.shared.seam import Confirm
from office_365_mcp.tools import outlook_cancel_event as canceller
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
    kind: str = "singleInstance",
) -> dict[str, object]:
    return {
        "id": _EVENT_ID,
        "subject": subject,
        "bodyPreview": "",
        "start": {"dateTime": "2026-03-02T14:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-03-02T15:00:00.0000000", "timeZone": "UTC"},
        "isAllDay": False,
        "isCancelled": False,
        "type": kind,
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


async def _registered(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    canceller.register(mcp, transport)
    tool = await mcp.get_tool(canceller.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool


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

    @pytest.mark.parametrize(
        ("kind", "said"),
        [
            ("seriesMaster", "The cancellation applies to every occurrence of the series."),
            (
                "occurrence",
                "The cancellation applies only to this one date. The other occurrences of the "
                + "series stay as they are.",
            ),
            (
                "exception",
                "The cancellation applies only to this one date. The other occurrences of the "
                + "series stay as they are.",
            ),
        ],
    )
    async def test_the_question_says_how_much_of_a_series_the_cancel_reaches(
        self, client: GraphServiceClient, graph: respx.MockRouter, kind: str, said: str
    ) -> None:
        _ = _reads(graph, _event(subject="Weekly sync", attendees=[_attendee(_ADA)], kind=kind))
        _ = _cancels(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _cancel(client, confirm=capturing)

        assert asked == [
            f"Cancel 'Weekly sync'? {said} Microsoft mails a cancellation to {_ADA}, and this "
            + "connector cannot recall it."
        ]

    async def test_a_series_master_with_nobody_on_it_is_cancelled_without_asking_and_says_so(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(kind="seriesMaster", attendees=[]))
        cancel = _cancels(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        answer = await _cancel(client, confirm=counting)

        assert asked == [], "cancelling a series with nobody on it interrupted the user"
        assert cancel.call_count == 1
        assert answer.series_master is True
        assert answer.notified is False

    async def test_the_question_about_a_single_event_names_no_series(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(subject="Weekly sync", attendees=[_attendee(_ADA)]))
        _ = _cancels(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _cancel(client, confirm=capturing)

        assert asked == [
            f"Cancel 'Weekly sync'? Microsoft mails a cancellation to {_ADA}, and this connector "
            + "cannot recall it."
        ]


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
        assert answer.series_master is False

    async def test_an_event_with_nobody_on_it_reports_notified_false(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _event(attendees=[]))

        answer = await _cancel(client)

        assert answer.attendees == []
        assert answer.notified is False

    async def test_a_series_master_with_an_attendee_is_reported_as_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _event(kind="seriesMaster", attendees=[_attendee(_ADA)]))

        answer = await _cancel(client)

        assert answer.series_master is True
        assert answer.notified is True

    @pytest.mark.parametrize("kind", ["singleInstance", "occurrence", "exception"])
    async def test_an_event_that_is_not_a_master_is_not_reported_as_a_series(
        self, client: GraphServiceClient, graph: respx.MockRouter, kind: str
    ) -> None:
        _ = _ready(graph, _event(kind=kind))

        answer = await _cancel(client)

        assert answer.series_master is False


class TestHowItDescribesItself:
    async def test_the_description_is_a_lead_and_a_few_notes_of_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        lead, separator, notes = description.partition("\n\nNotes:\n")
        assert separator, "the description has no Notes section"
        assert lead.strip() != ""
        assert 1 <= len([line for line in notes.splitlines() if line.startswith("- ")]) <= 4
        assert 45 <= len(description.split()) <= 210

    async def test_the_description_says_who_is_mailed_and_names_the_sibling_tools(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        assert "Cancels one event that the signed-in user organizes." in description
        assert "moves the event to Deleted Items" in description
        assert "mails each attendee a cancellation with the optional comment" in description
        assert "Nothing here can recall the cancellation." in description
        assert "If this deployment exposes outlook_delete_event" in description
        assert (
            "outlook_respond_to_invite declines an event that somebody else organizes."
            in description
        )
        assert "This tool refuses an event that the user does not organize." in description

    async def test_the_description_asks_the_user_to_agree_in_the_words_of_the_other_tools(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert (
            "This tool asks the user to agree before it cancels an event that has an attendee. "
            + "This tool cancels nothing unless the user agrees. This tool cancels an event "
            + "without that agreement only when the event has no attendee."
        ) in (tool.description or "")

    async def test_the_description_says_how_far_a_cancel_of_a_series_reaches(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        assert "The `uri` of a series master cancels every occurrence of the series." in description
        assert "The `uri` of one occurrence cancels only that date." in description
        assert "`series_master` true when the cancel reached the whole series" in description

    async def test_the_description_says_what_to_do_after_a_timeout(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "If a call times out, do not call this tool again first. A cancellation can already "
            + "be out."
        ) in description
        assert (
            "Before you call again, make sure that outlook_read_event still shows the event."
            in description
        )

    def test_the_series_master_field_has_the_one_description_of_the_series_fact(self) -> None:
        assert CancelledEvent.model_fields["series_master"].description == SERIES_MASTER_FIELD
