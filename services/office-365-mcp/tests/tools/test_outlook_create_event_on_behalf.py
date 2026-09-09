"""Every payload here is synthesised. No calendar, event or address came from a real mailbox."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from fastmcp.tools import Tool
from mcp.types import ElicitResult, InputRequiredResult
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field, TypeAdapter
from respx.models import Call

from office_365_mcp.graph_client import (
    GraphForbidden,
    GraphNotFound,
    GraphThrottled,
    GraphUnavailable,
)
from office_365_mcp.shared.calendar import (
    CALENDAR_FIELDS,
    MAX_ATTENDEES,
    MAX_LOCATION_CHARACTERS,
    MAX_ZONE_CHARACTERS,
    NOBODY_INVITED_BUT_A_PLACE,
    EventDraft,
    transaction_id_for,
)
from office_365_mcp.shared.handles import CalendarHandle, EventHandle, event_handle
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm
from office_365_mcp.tools import outlook_create_event_on_behalf as creator
from office_365_mcp.tools.outlook_create_event_on_behalf import CreatedEventOnBehalf

_CALENDAR_ID = "AAMkSYNTHETIC-cal-0001="
_OTHER_CALENDAR_ID = "AAMkSYNTHETIC-cal-0002="
_EVENT_ID = "AAMkAGI2SYNTHETIC-immutable-0001="

_CALENDAR_REF = CalendarHandle(_CALENDAR_ID).uri
_OTHER_CALENDAR_REF = CalendarHandle(_OTHER_CALENDAR_ID).uri

# The SDK percent-encodes the id into the path, so this is what the decoded handle comes back as.
_CALENDAR_PATH = "/me/calendars/AAMkSYNTHETIC-cal-0001%3D"
_OTHER_CALENDAR_PATH = "/me/calendars/AAMkSYNTHETIC-cal-0002%3D"
_EVENTS_PATH = f"{_CALENDAR_PATH}/events"
_OTHER_EVENTS_PATH = f"{_OTHER_CALENDAR_PATH}/events"

# The own-calendar route. Nothing in this file ever reaches it.
_MY_EVENTS_PATH = "/me/events"

_OWNER_NAME = "Alex Wilber"
_OWNER = "alex@example.invalid"
_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"
_PAM = "pam@example.invalid"

_SUBJECT = "Pricing review"
_STARTS_AT = "2026-03-02T14:00"
_ENDS_AT = "2026-03-02T15:00"

_WEB_LINK = "https://outlook.office365.invalid/owa/?itemid=synthetic-event&path=/calendar/item"
_JOIN_URL = "https://teams.microsoft.invalid/l/meetup-join/19%3ameeting_SYNTHETIC%40thread.v2/0"

# The draft `_called`'s own arguments compose, spelled out here so the id a confirmation is bound
# to can be named without reaching into the tool's private composer.
_DRAFT = EventDraft(
    subject=_SUBJECT,
    starts_at=_STARTS_AT,
    ends_at=_ENDS_AT,
    time_zone="UTC",
    attendees=(),
    optional_attendees=(),
    body_html=None,
    location=None,
    all_day=False,
    online_meeting=False,
)

# What the answer is bound to and what Graph is told to dedupe on: one string for both.
_TRANSACTION = transaction_id_for(_CALENDAR_ID, _DRAFT)


def _calendar_payload(
    *,
    calendar_id: str = _CALENDAR_ID,
    name: str | None = _OWNER_NAME,
    owner_name: str | None = _OWNER_NAME,
    owner: str | None = _OWNER,
    can_edit: bool | None = True,
    providers: Sequence[str] | None = ("teamsForBusiness",),
) -> dict[str, object]:
    """A delegated calendar as Microsoft lists it: named after its owner, canShare false.
    providers is None when the payload carries no allowedOnlineMeetingProviders key at all."""
    payload: dict[str, object] = {
        "id": calendar_id,
        "name": name,
        "owner": None if owner is None else {"name": owner_name, "address": owner},
        "canEdit": can_edit,
        "canShare": False,
        "canViewPrivateItems": False,
        "isDefaultCalendar": False,
        "isTallyingResponses": True,
        "defaultOnlineMeetingProvider": "teamsForBusiness",
    }
    if providers is not None:
        payload["allowedOnlineMeetingProviders"] = list(providers)
    return payload


def _attendee(address: str, *, kind: str = "required", response: str = "none") -> dict[str, object]:
    return {
        "type": kind,
        "status": {"response": response, "time": "0001-01-01T00:00:00Z"},
        "emailAddress": {"name": None, "address": address},
    }


def _created_payload(
    *,
    event_id: str = _EVENT_ID,
    subject: str | None = _SUBJECT,
    attendees: Sequence[Mapping[str, object]] = (),
    organizer: str | None = _OWNER,
    start: Mapping[str, object] | None = None,
    end: Mapping[str, object] | None = None,
    all_day: bool | None = False,
    location: str | None = None,
    online_meeting: bool | None = False,
    join_url: str | None = None,
    transaction_id: str | None = "SYNTHETIC-transaction-0001",
    web_link: str | None = _WEB_LINK,
) -> dict[str, object]:
    """Graph's 201. Microsoft renders both bounds in UTC when nothing asks for another zone."""
    return {
        "id": event_id,
        "subject": subject,
        "start": dict(start)
        if start is not None
        else {"dateTime": "2026-03-02T14:00:00.0000000", "timeZone": "UTC"},
        "end": dict(end)
        if end is not None
        else {"dateTime": "2026-03-02T15:00:00.0000000", "timeZone": "UTC"},
        "isAllDay": all_day,
        "location": None if location is None else {"displayName": location},
        "isOnlineMeeting": online_meeting,
        "onlineMeeting": None if join_url is None else {"joinUrl": join_url},
        "organizer": None
        if organizer is None
        else {"emailAddress": {"name": _OWNER_NAME, "address": organizer}},
        "attendees": [dict(one) for one in attendees],
        "transactionId": transaction_id,
        "webLink": web_link,
    }


def _message_envelope() -> dict[str, object]:
    """Microsoft's delegated-create walkthrough answers step 2 with an eventMessage envelope:
    the event under an event key, under its own id, that the SDK deserializes into Event too."""
    return {
        "@odata.type": "#microsoft.graph.eventMessage",
        "id": "AAMkADADSYNTHETIC-message-0001=",
        "subject": _SUBJECT,
        "event": _created_payload(),
    }


def _reads(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    return graph.get(_CALENDAR_PATH).mock(
        return_value=httpx.Response(
            200, json=payload if payload is not None else _calendar_payload()
        )
    )


def _creates(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    return graph.post(_EVENTS_PATH).mock(
        return_value=httpx.Response(
            201, json=payload if payload is not None else _created_payload()
        )
    )


def _ready(
    graph: respx.MockRouter,
    *,
    calendar: dict[str, object] | None = None,
    created: dict[str, object] | None = None,
) -> respx.Route:
    _ = _reads(graph, calendar)
    return _creates(graph, created)


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    """A person who said no, in the shape a refusal takes here: answered, never raised."""
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return "No event was created. The person did not agree."


async def _cannot_ask(question: str, about: str) -> str | None:
    """A client with no elicitation support, which `person_confirms` reports as a refusal too."""
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return "No event was created. The MCP client does not support elicitation."


def _context(answer: object) -> Context:
    """request_context is None here, which person_confirms reads as an era it cannot name and
    asks over the back-channel anyway."""

    class _Client:
        request_context: None = None

        async def elicit(self, message: str, response_type: object = None) -> object:
            assert message
            assert response_type is not None, "the caller must say what it expects back"
            if isinstance(answer, Exception):
                raise answer
            return answer

    return cast("Context", cast("object", _Client()))


@dataclass(frozen=True, slots=True)
class _Negotiated:
    """The one thing `person_confirms` reads off a request context: which era was negotiated."""

    protocol_version: str


def _modern_context(
    *, answers: Mapping[str, object] | None = None, state: str | None = None
) -> Context:
    """A 2026-07-28 connection has no channel to elicit over, so elicit raises rather than
    answering when a call reaches for it."""

    class _Client:
        request_context: _Negotiated = _Negotiated(LATEST_MODERN_VERSION)

        def __init__(self) -> None:
            self.input_responses: Mapping[str, object] | None = answers
            self.request_state: str | None = state

        async def elicit(self, message: str, response_type: object = None) -> object:
            _ = (message, response_type)
            raise AssertionError("a 2026-07-28 connection was asked over the back-channel")

    return cast("Context", cast("object", _Client()))


def _accepting(asked: InputRequiredResult, answer: str = "create") -> Mapping[str, object]:
    """The key is read off round one rather than hardcoded, so the two rounds are proved to
    agree with each other rather than both agreeing with this file."""
    assert asked.input_requests is not None, "the question asked for nothing at all"
    (key,) = asked.input_requests

    return {key: ElicitResult(action="accept", content={"value": answer})}


async def _create(client: GraphServiceClient, **overrides: object) -> CreatedEventOnBehalf:
    """Narrowed to the event; this era answers inline, so a returned question would mean the
    test no longer tests what it says."""
    answered = await _called(client, **overrides)
    assert isinstance(answered, CreatedEventOnBehalf), (
        "the tool answered with a question rather than an event"
    )
    return answered


async def _called(
    client: GraphServiceClient, **overrides: object
) -> CreatedEventOnBehalf | InputRequiredResult:
    arguments: dict[str, object] = {
        "calendar_ref": _CALENDAR_REF,
        "subject": _SUBJECT,
        "starts_at": _STARTS_AT,
        "ends_at": _ENDS_AT,
        "time_zone": "UTC",
        "attendees": [],
        "confirm": _agrees,
    }
    arguments.update(overrides)
    return await creator.create_event_on_behalf(
        client,
        calendar_ref=cast("str", arguments["calendar_ref"]),
        subject=cast("str", arguments["subject"]),
        starts_at=cast("str", arguments["starts_at"]),
        ends_at=cast("str", arguments["ends_at"]),
        time_zone=cast("str", arguments["time_zone"]),
        attendees=cast("Sequence[str]", arguments["attendees"]),
        optional_attendees=cast("Sequence[str]", arguments.get("optional_attendees", ())),
        body_html=cast("str | None", arguments.get("body_html")),
        location=cast("str | None", arguments.get("location")),
        all_day=cast("bool", arguments.get("all_day", False)),
        online_meeting=cast("bool", arguments.get("online_meeting", False)),
        confirm=cast("Confirm", arguments["confirm"]),
    )


async def _asked(client: GraphServiceClient, **overrides: object) -> str:
    questions: list[str] = []

    async def capturing(question: str, about: str) -> str | None:
        assert about, "the answer was bound to nothing"
        questions.append(question)
        return None

    _ = await _create(client, confirm=capturing, **overrides)

    assert len(questions) == 1, "this tool asks exactly one question per call"
    return questions[0]


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _invited(sent: dict[str, object]) -> list[tuple[str, str]]:
    attendees = cast("list[dict[str, object]]", sent.get("attendees", []))
    return [
        (
            cast("str", cast("dict[str, object]", one["emailAddress"])["address"]),
            cast("str", one["type"]),
        )
        for one in attendees
    ]


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    creator.register(mcp, transport)
    tool = await mcp.get_tool(creator.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _undescribed(schema: Mapping[str, object]) -> list[str]:
    nested = cast("Mapping[str, Mapping[str, object]]", schema.get("$defs", {}))
    found: list[str] = []
    for shape, node in [(creator.CreatedEventOnBehalf.__name__, schema), *nested.items()]:
        properties = cast("Mapping[str, Mapping[str, object]]", node.get("properties", {}))
        found.extend(
            f"{shape}.{field}"
            for field, published in properties.items()
            if not published.get("description")
        )
    return sorted(found)


class TestTheCalendarItAddresses:
    async def test_it_creates_the_event_on_the_calendar_the_handle_names(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)
        other = graph.post(_OTHER_EVENTS_PATH).mock(
            return_value=httpx.Response(201, json=_created_payload())
        )

        _ = await _create(client)

        assert create.call_count == 1
        assert other.call_count == 0, "a handle addresses one calendar, not another"

    async def test_it_never_posts_to_the_signed_in_users_own_calendar(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`POST /me/events` is the own-calendar route. Reaching it here puts the event in
        the wrong mailbox, under the wrong name, and answer 201 while doing it."""
        create = _ready(graph)
        mine = graph.post(_MY_EVENTS_PATH).mock(
            return_value=httpx.Response(201, json=_created_payload())
        )

        _ = await _create(client)

        assert create.call_count == 1
        assert mine.call_count == 0, "the event was created on the signed-in user's own calendar"

    async def test_it_reads_the_calendar_and_then_creates_and_makes_no_other_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        create = _creates(graph)

        _ = await _create(client)

        assert read.call_count == 1
        assert create.call_count == 1
        assert len(graph.calls) == 2, "a delegated create costs the pre-read and the create"
        made = cast("Sequence[Call]", graph.calls)
        assert [call.request.method for call in made] == ["GET", "POST"]

    async def test_the_pre_read_asks_for_the_shared_calendar_projection(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """One projection across every calendar tool. A field selected here and not there is a row
        that reports `can_edit` from one tool and null from another."""
        read = _reads(graph)
        _ = _creates(graph)

        _ = await _create(client)

        selected = read.calls.last.request.url.params["$select"]
        assert selected.split(",") == list(CALENDAR_FIELDS)

    async def test_the_create_declares_the_immutable_id_space_the_handle_is_minted_in(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The answer mints an event handle out of the 201, and Graph reads an id in whichever
        space the request that produced it declared."""
        create = _ready(graph)

        _ = await _create(client)

        assert create.calls.last.request.headers["prefer"] == 'IdType="ImmutableId"'

    async def test_neither_request_asks_graph_to_render_times_in_a_zone(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`Prefer: outlook.timezone` makes Graph render every time of the answer in one zone.
        This connector converts with `zoneinfo` instead, and the two together disagree."""
        read = _reads(graph)
        create = _creates(graph)

        _ = await _create(client)

        assert "outlook.timezone" not in read.calls.last.request.headers.get("prefer", "")
        assert "outlook.timezone" not in create.calls.last.request.headers.get("prefer", "")


class TestWhatItSendsToGraph:
    async def test_it_sends_the_subject_the_bounds_and_the_zone_it_was_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The zone reaches Graph as written. Microsoft accepts every Windows name and a fixed
        list of IANA names here, and translating one changes which instant the event is at."""
        create = _ready(graph)

        _ = await _create(client, time_zone="W. Europe Standard Time")

        sent = _sent(create)
        assert sent["subject"] == _SUBJECT
        assert sent["start"] == {"dateTime": _STARTS_AT, "timeZone": "W. Europe Standard Time"}
        assert sent["end"] == {"dateTime": _ENDS_AT, "timeZone": "W. Europe Standard Time"}

    async def test_the_two_attendee_lists_reach_graph_as_required_and_optional(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)

        _ = await _create(client, attendees=[_ADA], optional_attendees=[_GRACE, _PAM])

        assert _invited(_sent(create)) == [
            (_ADA, "required"),
            (_GRACE, "optional"),
            (_PAM, "optional"),
        ]

    async def test_an_empty_attendee_list_sends_no_attendees_key_at_all(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`attendees: []` tells Microsoft there are no attendees, and no key tells it nothing.
        The two are different requests, and only the second is what an appointment is."""
        create = _ready(graph)

        _ = await _create(client, attendees=[])

        assert "attendees" not in _sent(create)

    @pytest.mark.parametrize(
        "absent", ["hideAttendees", "recurrence", "responseRequested", "attachments"]
    )
    async def test_nothing_it_sends_carries_a_property_no_argument_offers(
        self, client: GraphServiceClient, graph: respx.MockRouter, absent: str
    ) -> None:
        create = _ready(graph)

        _ = await _create(client, attendees=[_ADA])

        assert absent not in _sent(create)

    async def test_two_identical_calls_send_one_transaction_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft's only defense against a duplicate create is this client-set id, and an id
        that changes per call tells Microsoft the second create is a different event."""
        create = _ready(graph)

        _ = await _create(client)
        first = _sent(create)["transactionId"]
        _ = await _create(client)

        assert first == _sent(create)["transactionId"]
        assert isinstance(first, str) and first, "no transactionId reached Graph at all"

    async def test_the_same_event_on_another_calendar_is_another_transaction(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Two calendars are two events. An id that ignores the calendar makes the second
        create look like a retry of the first."""
        create = _ready(graph)
        other_read = graph.get(_OTHER_CALENDAR_PATH).mock(
            return_value=httpx.Response(200, json=_calendar_payload(calendar_id=_OTHER_CALENDAR_ID))
        )
        other_create = graph.post(_OTHER_EVENTS_PATH).mock(
            return_value=httpx.Response(201, json=_created_payload())
        )

        _ = await _create(client)
        _ = await _create(client, calendar_ref=_OTHER_CALENDAR_REF)

        assert other_read.call_count == 1
        assert _sent(create)["transactionId"] != _sent(other_create)["transactionId"]

    async def test_a_body_and_a_location_reach_graph_when_they_are_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)

        _ = await _create(client, body_html="<p>Numbers attached below.</p>", location="Room 3")

        sent = _sent(create)
        assert sent["body"] == {"contentType": "html", "content": "<p>Numbers attached below.</p>"}
        assert sent["location"] == {"displayName": "Room 3"}

    async def test_an_online_meeting_is_asked_for_by_provider(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)

        _ = await _create(client, online_meeting=True)

        sent = _sent(create)
        assert sent["isOnlineMeeting"] is True
        assert sent["onlineMeetingProvider"] == "teamsForBusiness"


class TestThePersonBetweenTheRequestAndTheCalendar:
    async def test_a_refusal_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)

        with pytest.raises(ToolError, match="No event was created"):
            _ = await _create(client, confirm=_refuses)

        assert create.call_count == 0, "a declined create still reached the calendar"

    async def test_a_client_that_cannot_ask_creates_nothing_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)

        with pytest.raises(ToolError, match="elicitation"):
            _ = await _create(client, confirm=_cannot_ask)

        assert create.call_count == 0

    async def test_the_question_is_asked_even_when_nobody_is_invited(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about, "the answer was bound to nothing"
            asked.append(question)
            return None

        _ = await _create(client, attendees=[], confirm=capturing)

        assert len(asked) == 1, "an event on somebody else's calendar was created unasked"
        assert "no invitations" in asked[0], "the question did not say that nobody is told"
        assert create.call_count == 1

    async def test_the_question_comes_after_the_read_and_before_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> str | None:
            assert about, "the answer was bound to nothing"
            assert question
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await _create(client, confirm=watching)

        assert calls_when_asked == [1], "asked before the read, or after the create"
        assert create.call_count == 1

    async def test_the_question_names_the_owner_the_subject_and_both_bounds(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about, "the answer was bound to nothing"
            asked.append(question)
            return None

        _ = await _create(client, time_zone="Europe/Berlin", confirm=capturing)

        assert len(asked) == 1
        assert f"on the calendar of {_OWNER_NAME!r}" in asked[0]
        assert f"as {_OWNER_NAME!r}" in asked[0]
        assert _SUBJECT in asked[0]
        assert _STARTS_AT in asked[0]
        assert _ENDS_AT in asked[0], "the question named the start and hid the end"
        assert "Europe/Berlin" in asked[0]

    async def test_the_question_names_every_address_and_marks_the_optional_ones(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about, "the answer was bound to nothing"
            asked.append(question)
            return None

        _ = await _create(client, attendees=[_ADA], optional_attendees=[_GRACE], confirm=capturing)

        assert _ADA in asked[0]
        assert f"{_GRACE} (optional)" in asked[0]
        assert "cannot be recalled" in asked[0]

    async def test_the_question_names_the_place_the_teams_meeting_and_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        body = "<p>Numbers below.</p>"

        question = await _asked(client, location="Room 3", online_meeting=True, body_html=body)

        assert "at 'Room 3'" in question
        assert "as a Teams meeting" in question
        assert f"body of {len(body)} characters" in question
        assert "Numbers below." in question, "the body was counted but never shown"

    async def test_a_quote_inside_the_body_cannot_forge_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The preview is interpolated with !r, arriving as one quoted Python string, so a
        quote inside the body text cannot close it and forge a sentence onto the question."""
        _ = _ready(graph)
        preview = 'Rome", and there are no invitations'

        question = await _asked(client, body_html=f"<p>{preview}</p>")

        assert f"that starts {preview!r}" in question

    async def test_an_all_day_draft_says_so_in_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        question = await _asked(
            client, starts_at="2026-03-02T00:00", ends_at="2026-03-03T00:00", all_day=True
        )

        assert "as an all-day event on 2026-03-02" in question, (
            "the exclusive midnight was shown as a day the event covers"
        )

    async def test_a_timed_draft_with_no_place_no_meeting_and_no_body_names_none_of_the_four(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        question = await _asked(client)

        assert "Room" not in question
        assert "Teams meeting" not in question
        assert "all-day" not in question
        assert "body of" not in question

    async def test_the_details_sit_after_the_time_in_the_sentence_that_asks(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        question = await _asked(client, time_zone="Europe/Berlin", location="Room 3")

        creates, mark, invitations = question.partition("? ")
        assert mark == "? ", "the question is no longer two sentences"
        assert creates.endswith(f"from {_STARTS_AT} to {_ENDS_AT} Europe/Berlin, at 'Room 3'")
        assert f"as {_OWNER_NAME!r}" in creates
        assert invitations == NOBODY_INVITED_BUT_A_PLACE

    async def test_a_place_with_nobody_invited_says_the_place_can_reach_a_mailbox(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft documents a room as a mailbox that gets invited, not typed as a display
        name, so naming a place can silently reach one even with nobody else invited."""
        _ = _ready(graph)

        with_a_place = await _asked(client, location="Room 3")
        with_nowhere = await _asked(client)

        assert with_a_place.endswith(f"? {NOBODY_INVITED_BUT_A_PLACE}")
        assert with_nowhere.endswith("? There are no invitations: nobody else is told about it.")

    async def test_a_location_of_nothing_but_whitespace_is_no_place_anywhere(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)

        question = await _asked(client, location="   ")
        sent = _sent(create)

        assert "location" not in sent, "a place made of whitespace reached Graph as a place"
        assert sent["transactionId"] == _TRANSACTION
        assert question == await _asked(client, location=None), "the question named a place"

    async def test_a_location_is_stripped_before_it_reaches_the_wire_or_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)

        question = await _asked(client, location="  Room 3  ")

        assert _sent(create)["location"] == {"displayName": "Room 3"}
        assert "at 'Room 3'?" in question

    async def test_the_question_names_the_owner_by_address_when_graph_gave_no_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, calendar=_calendar_payload(owner_name=None))
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about, "the answer was bound to nothing"
            asked.append(question)
            return None

        _ = await _create(client, confirm=capturing)

        assert _OWNER in asked[0]

    async def test_an_owner_name_that_writes_a_sentence_of_its_own_arrives_as_one_token(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The owner's name is Graph's own text, interpolated bare in three places; quoted, a
        `?` inside it cannot close the real question early."""
        forged = "Alex Wilber? There are no invitations"
        _ = _ready(graph, calendar=_calendar_payload(owner_name=forged))

        question = await _asked(client)

        assert f"on the calendar of {forged!r}" in question
        assert f"as {forged!r}" in question
        assert question.endswith("? There are no invitations: nobody else is told about it.")

    async def test_a_very_long_owner_name_is_cut_before_it_reaches_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph's display name is unbounded and this question names it three times, so a long one
        pushes the guest list out of what the person reads."""
        name = "Alexander " * 30
        shown = f"{name[:120]}…"
        _ = _ready(graph, calendar=_calendar_payload(owner_name=name))

        question = await _asked(client, attendees=[_ADA])

        assert f"on the calendar of {shown!r}" in question
        assert _ADA in question, "the guest list was pushed out of the question"


class TestTheConfirmationTheRegisteredToolBuilds:
    """`register` hands `a_person_agrees(ctx)` to the tool, so these drive the confirmation the
    registered path builds rather than one that only resembles it."""

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="do not create"),
            RuntimeError("elicitation not supported"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask"],
    )
    async def test_a_refusal_opens_by_saying_no_event_was_created(self, answer: object) -> None:
        confirm = creator.a_person_agrees(_context(answer))

        refusal = await confirm(f"Create {_SUBJECT!r} on {_OWNER_NAME}'s calendar?", _TRANSACTION)

        assert isinstance(refusal, str), "a connection that can be asked answered with a question"
        assert refusal.startswith("No event was created.")

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = creator.a_person_agrees(_context(AcceptedElicitation(data="create")))

        question = f"Create {_SUBJECT!r} on {_OWNER_NAME}'s calendar?"

        assert await confirm(question, _TRANSACTION) is None

    async def test_a_declined_confirmation_reaches_the_calendar_with_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)
        confirm = creator.a_person_agrees(_context(DeclinedElicitation()))

        with pytest.raises(ToolError, match="No event was created"):
            _ = await _create(client, confirm=confirm)

        assert create.call_count == 0


class TestTheQuestionOnAConnectionWithNoBackChannel:
    """A 2026-07-28 connection has no channel to ask a person over (SEP-2577): the tool returns
    the question, and the client resubmits with the answer, through the real person_confirms."""

    async def test_round_one_reads_the_calendar_asks_and_posts_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        create = _creates(graph)

        asked = await _called(client, confirm=creator.a_person_agrees(_modern_context()))

        assert isinstance(asked, InputRequiredResult), "the tool answered without asking anybody"
        assert asked.request_state == _TRANSACTION, (
            "the question was bound to something other than the draft this call would write"
        )
        assert read.call_count == 1, "the owner's name comes off the read, so it happens first"
        assert create.call_count == 0, "an unconfirmed create reached somebody else's calendar"

    async def test_round_two_creates_once_under_the_id_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)

        asked = await _called(client, confirm=creator.a_person_agrees(_modern_context()))
        assert isinstance(asked, InputRequiredResult)
        answered = await _called(
            client,
            confirm=creator.a_person_agrees(
                _modern_context(answers=_accepting(asked), state=asked.request_state)
            ),
        )

        assert isinstance(answered, CreatedEventOnBehalf), "an agreed create asked again instead"
        assert create.call_count == 1, f"the agreed create posted {create.call_count} times"
        assert _sent(create)["transactionId"] == _TRANSACTION

    async def test_an_answer_bound_to_another_request_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)

        asked = await _called(client, confirm=creator.a_person_agrees(_modern_context()))
        assert isinstance(asked, InputRequiredResult)

        with pytest.raises(ToolError, match="different request"):
            _ = await _called(
                client,
                confirm=creator.a_person_agrees(
                    _modern_context(answers=_accepting(asked), state="a-different-id")
                ),
            )

        assert create.call_count == 0, "a create nobody agreed to reached the calendar"

    async def test_a_second_round_the_person_declined_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)

        asked = await _called(client, confirm=creator.a_person_agrees(_modern_context()))
        assert isinstance(asked, InputRequiredResult)
        assert asked.input_requests is not None, "the question asked for nothing at all"
        (key,) = asked.input_requests

        with pytest.raises(ToolError, match="did not agree") as raised:
            _ = await _called(
                client,
                confirm=creator.a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="decline")}, state=asked.request_state
                    )
                ),
            )

        assert str(raised.value).startswith("No event was created.")
        assert create.call_count == 0, "a declined create reached somebody else's calendar"

    async def test_the_registry_example_takes_two_rounds_although_it_invites_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """This tool's question is not conditional on the attendee lists, so its own published
        example asks too, unlike the own-calendar create whose example posts on round one."""
        create = _ready(graph)
        example = dict(creator.GRAPH_CALL_EXAMPLE)

        assert example["attendees"] == [], "the example this is about now invites somebody"

        asked = await _called(client, **example, confirm=creator.a_person_agrees(_modern_context()))

        assert isinstance(asked, InputRequiredResult), (
            "the published example wrote into somebody else's day without asking"
        )
        assert create.call_count == 0

        answered = await _called(
            client,
            **example,
            confirm=creator.a_person_agrees(
                _modern_context(answers=_accepting(asked), state=asked.request_state)
            ),
        )

        assert isinstance(answered, CreatedEventOnBehalf)
        assert create.call_count == 1, "the example took one round or more than two"


class TestTheCalendarsItRefusesToWriteTo:
    async def test_a_read_only_calendar_is_refused_before_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph, calendar=_calendar_payload(can_edit=False))

        with pytest.raises(ToolError, match="read-only"):
            _ = await _create(client)

        assert create.call_count == 0, "a read-only calendar was written to anyway"

    async def test_the_read_only_refusal_says_nothing_was_created(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, calendar=_calendar_payload(can_edit=False))

        with pytest.raises(ToolError, match="NO EVENT WAS CREATED"):
            _ = await _create(client)

    async def test_a_read_only_calendar_is_never_put_to_a_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, calendar=_calendar_payload(can_edit=False))
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about, "the answer was bound to nothing"
            asked.append(question)
            return None

        with pytest.raises(ToolError):
            _ = await _create(client, confirm=capturing)

        assert asked == [], "a person was asked about a calendar that refuses the write"

    async def test_a_calendar_graph_said_nothing_about_is_attempted_rather_than_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Null is not false. Only Microsoft knows whether a write lands, and a null `canEdit` is
        this connector knowing nothing rather than knowing no."""
        create = _ready(graph, calendar=_calendar_payload(can_edit=None))

        _ = await _create(client)

        assert create.call_count == 1

    async def test_a_teams_meeting_a_calendar_lists_no_provider_for_is_refused_before_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph, calendar=_calendar_payload(providers=["skypeForBusiness"]))

        with pytest.raises(ToolError, match="skypeForBusiness"):
            _ = await _create(client, online_meeting=True)

        assert create.call_count == 0

    async def test_a_teams_meeting_a_calendar_lists_no_provider_for_is_never_put_to_a_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The pre-read decides this refusal, so it lands before anybody is asked. Asking somebody
        to confirm a create that cannot happen spends their attention on nothing, and teaches them
        to agree without reading."""
        create = _ready(graph, calendar=_calendar_payload(providers=["skypeForBusiness"]))
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about, "the answer was bound to nothing"
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="skypeForBusiness"):
            _ = await _create(client, online_meeting=True, confirm=capturing)

        assert asked == [], "a person was asked about a Teams meeting that calendar refuses"
        assert create.call_count == 0, "a calendar that takes no Teams meeting was written to"

    @pytest.mark.parametrize("providers", [(), None], ids=["empty-list", "no-key"])
    async def test_a_calendar_that_names_no_provider_is_attempted_rather_than_refused(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        providers: Sequence[str] | None,
    ) -> None:
        create = _ready(graph, calendar=_calendar_payload(providers=providers))

        _ = await _create(client, online_meeting=True)

        assert create.call_count == 1

    async def test_a_calendar_that_takes_no_teams_meeting_takes_an_event_without_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph, calendar=_calendar_payload(providers=["skypeForBusiness"]))

        _ = await _create(client)

        assert create.call_count == 1


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "calendar_ref",
        [
            "outlook:///events/AAMkSYNTHETIC-cal-0001%3D/AAMkAGI2SYNTHETIC-immutable-0001%3D",
            "outlook:///folders/AQMkADAwSYNTHETIC-folder",
            "outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D",
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
            "outlook:///calendars/",
            "outlook:///calendars/%20",
            "AAMkSYNTHETIC-cal-0001=",
            "Alex Wilber",
            _OWNER,
        ],
    )
    async def test_anything_that_is_not_a_calendar_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, calendar_ref: str
    ) -> None:
        _ = _ready(graph)

        with pytest.raises(ToolError):
            _ = await _create(client, calendar_ref=calendar_ref)

        assert len(graph.calls) == 0, "a refused argument never reaches the mailbox"

    async def test_the_handle_refusal_points_at_the_tool_that_mints_one(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="outlook_list_calendars"):
            _ = await _create(client, calendar_ref="Alex Wilber")

    @pytest.mark.parametrize(
        "moment",
        [
            "2026-03-02T14:00:00+02:00",
            "2026-03-02T14:00:00Z",
            "2026-03-02T14:00Z",
            "2026-03-02",
            "14:00",
            "2026-03-02 14:00",
            "2026-W10-1",
            "2026-03-02T14",
            "20260302T140000",
            "tomorrow at 2",
            "2026-02-30T14:00",
            "2026-03-02T25:00",
        ],
    )
    async def test_a_start_that_is_not_a_local_wall_clock_time_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, moment: str
    ) -> None:
        """datetime.fromisoformat reads these shapes since Python 3.11 widened it to all of ISO
        8601, and an accepted string reaches Exchange exactly as the caller wrote it."""
        _ = _ready(graph)

        with pytest.raises(ToolError):
            _ = await _create(client, starts_at=moment, ends_at="2026-03-02T23:00")

        assert len(graph.calls) == 0

    async def test_an_end_that_is_not_a_local_wall_clock_time_is_refused_by_its_own_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        with pytest.raises(ToolError, match="`ends_at`"):
            _ = await _create(client, ends_at="2026-03-02T15:00:00Z")

        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        "ends_at", ["2026-03-02T14:00", "2026-03-02T13:00", "2026-03-01T14:00"]
    )
    async def test_an_event_that_ends_before_it_begins_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, ends_at: str
    ) -> None:
        _ = _ready(graph)

        with pytest.raises(ToolError, match="cannot end before it begins"):
            _ = await _create(client, ends_at=ends_at)

        assert len(graph.calls) == 0

    async def test_a_timed_event_longer_than_a_day_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        with pytest.raises(ToolError, match="timed event"):
            _ = await _create(client, ends_at="2026-03-04T15:00")

        assert len(graph.calls) == 0

    async def test_an_all_day_event_longer_than_two_weeks_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        with pytest.raises(ToolError, match="all-day event"):
            _ = await _create(
                client,
                starts_at="2026-03-02T00:00",
                ends_at="2026-04-02T00:00",
                all_day=True,
            )

        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        ("starts_at", "ends_at"),
        [
            ("2026-03-02T14:00", "2026-03-03T00:00"),
            ("2026-03-02T00:00", "2026-03-03T15:00"),
            ("2026-03-02T00:00:30", "2026-03-03T00:00"),
        ],
        ids=["start-at-two", "end-at-three", "start-half-a-minute-late"],
    )
    async def test_an_all_day_event_that_does_not_run_midnight_to_midnight_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, starts_at: str, ends_at: str
    ) -> None:
        """Microsoft requires both bounds of an all-day event at midnight, and Exchange answers
        anything else with a 400 that carries no advice about which bound was wrong."""
        _ = _ready(graph)

        with pytest.raises(ToolError, match="midnight to midnight"):
            _ = await _create(client, starts_at=starts_at, ends_at=ends_at, all_day=True)

        assert len(graph.calls) == 0

    async def test_the_all_day_refusal_names_both_values_it_was_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        with pytest.raises(ToolError, match="2026-03-02T14:00.+2026-03-03T15:00"):
            _ = await _create(
                client, starts_at="2026-03-02T14:00", ends_at="2026-03-03T15:00", all_day=True
            )

    async def test_a_span_a_timed_event_refuses_is_allowed_for_an_all_day_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)

        _ = await _create(
            client, starts_at="2026-03-02T00:00", ends_at="2026-03-05T00:00", all_day=True
        )

        assert create.call_count == 1

    @pytest.mark.parametrize(
        "address",
        [
            "Ada Lovelace <ada@example.invalid>",
            "ada@example.invalid, grace@example.invalid",
            "ada@example.invalid; grace@example.invalid",
            "Ada Lovelace",
            "ada@",
            "@example.invalid",
            "ada@ex ample.invalid",
            "ada@example@invalid",
            "   ",
        ],
    )
    async def test_an_attendee_that_is_not_one_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, address: str
    ) -> None:
        _ = _ready(graph)

        with pytest.raises(ToolError):
            _ = await _create(client, attendees=[address])

        assert len(graph.calls) == 0, "a refused address still reached the calendar"

    async def test_an_optional_attendee_is_held_to_the_same_rule_and_names_its_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        with pytest.raises(ToolError, match="`optional_attendees`"):
            _ = await _create(client, optional_attendees=["Grace Hopper <grace@example.invalid>"])

        assert len(graph.calls) == 0

    async def test_the_address_refusal_says_where_an_address_may_not_come_from(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="chosen by whoever"):
            _ = await _create(client, attendees=["Ada Lovelace"])

    async def test_surrounding_whitespace_is_trimmed_rather_than_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _ready(graph)

        _ = await _create(client, attendees=[f"  {_ADA}  "])

        assert _invited(_sent(create)) == [(_ADA, "required")]

    async def test_one_person_in_both_lists_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        with pytest.raises(ToolError, match="one list only"):
            _ = await _create(client, attendees=[_ADA], optional_attendees=[_ADA.upper()])

        assert len(graph.calls) == 0

    @pytest.mark.parametrize("argument", ["attendees", "optional_attendees"])
    async def test_the_same_person_twice_in_one_list_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, argument: str
    ) -> None:
        _ = _ready(graph)
        listed: dict[str, object] = {argument: [_ADA, _ADA.upper()]}

        with pytest.raises(ToolError, match="more than once"):
            _ = await _create(client, **listed)

        assert len(graph.calls) == 0

    async def test_more_addresses_than_the_two_lists_hold_together_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        required = [f"one{index}@example.invalid" for index in range(MAX_ATTENDEES - 5)]
        optional = [f"two{index}@example.invalid" for index in range(6)]

        with pytest.raises(ToolError, match=str(MAX_ATTENDEES)):
            _ = await _create(client, attendees=required, optional_attendees=optional)

        assert len(graph.calls) == 0

    @pytest.mark.parametrize("subject", ["", "x" * 256])
    async def test_a_subject_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient, subject: str
    ) -> None:
        assert subject != _SUBJECT
        with pytest.raises(AssertionError):
            _ = await _create(client, subject=subject)


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_answers_503_is_never_posted_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The SDK retries POST on 429/503/504 three times by default; a 503 after Graph
        already created the event would leave a duplicate meeting and a second invitation."""
        _ = _reads(graph)
        create = graph.post(_EVENTS_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _create(client, attendees=[_ADA])

        assert create.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_create_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        create = graph.post(_EVENTS_PATH).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "12"})
        )

        with pytest.raises(GraphThrottled):
            _ = await _create(client, attendees=[_ADA])

        assert create.call_count == 1


class TestWhatItAnswers:
    async def test_the_organizer_is_read_off_the_created_event_and_is_the_calendar_owner(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft puts the owner on the event and the delegate nowhere on it. The answer has to
        say so, because that name is what the attendees see."""
        _ = _ready(graph, created=_created_payload(organizer=_OWNER))

        answer = await _create(client)

        assert answer.organizer is not None
        assert answer.organizer.address == _OWNER

    async def test_the_attendees_are_read_off_the_created_event_and_never_echoed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Exchange composes this list itself, adding the owner and any `resource` row (a room
        or piece of equipment) now on the event; an echo of the arguments would miss both."""
        _ = _ready(
            graph,
            created=_created_payload(
                attendees=[
                    _attendee(_OWNER, response="organizer"),
                    _attendee(_ADA),
                    _attendee("room3@example.invalid", kind="resource", response="accepted"),
                ]
            ),
        )

        answer = await _create(client, attendees=[_ADA])

        assert [one.address for one in answer.attendees] == [
            _OWNER,
            _ADA,
            "room3@example.invalid",
        ]
        assert [one.kind for one in answer.attendees] == ["required", "required", "resource"]
        assert answer.attendees[0].response == "organizer"

    async def test_it_reports_invitations_when_microsoft_stored_somebody_to_tell(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, created=_created_payload(attendees=[_attendee(_ADA)]))

        answer = await _create(client, attendees=[_ADA])

        assert answer.invitations_sent is True

    async def test_an_appointment_nobody_was_told_about_reports_no_invitations(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft sends nothing for an event with no attendees, so the one honest reading of the
        201 is the stored list."""
        _ = _ready(graph, created=_created_payload(attendees=[]))

        answer = await _create(client, attendees=[])

        assert answer.invitations_sent is False

    async def test_the_calendar_owner_comes_off_the_read_that_happened_before_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The 201 of a create carries no calendar, so the only place the owner can come from is
        the pre-read. It is also the name to report back."""
        _ = _ready(graph, created=_created_payload(organizer=None))

        answer = await _create(client)

        assert answer.calendar_owner is not None
        assert answer.calendar_owner.address == _OWNER
        assert answer.calendar_owner.name == _OWNER_NAME
        assert answer.organizer is None

    async def test_a_calendar_graph_gave_no_owner_for_answers_null_rather_than_a_guess(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, calendar=_calendar_payload(owner=None))

        answer = await _create(client)

        assert answer.calendar_owner is None
        assert answer.calendar.owner is None

    async def test_the_calendar_it_answers_with_says_nothing_about_whose_it_is(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """This call reads no signed-in user, so `is_mine` is unknown rather than false: null means
        nobody compared, and false claims the calendar is somebody else's."""
        _ = _ready(graph)

        answer = await _create(client)

        assert answer.calendar.is_mine is None
        assert answer.calendar.can_edit is True

    async def test_the_handle_it_mints_carries_the_calendar_and_the_event(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        answer = await _create(client)

        assert answer.uri == EventHandle(_CALENDAR_ID, _EVENT_ID).uri
        handle = event_handle(answer.uri)
        assert handle is not None
        assert handle.calendar_id == _CALENDAR_ID
        assert handle.event_id == _EVENT_ID

    async def test_the_bounds_are_converted_into_the_zone_that_was_asked_for(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(
            graph,
            created=_created_payload(
                start={"dateTime": "2026-03-02T13:00:00.0000000", "timeZone": "UTC"},
                end={"dateTime": "2026-03-02T14:00:00.0000000", "timeZone": "UTC"},
            ),
        )

        answer = await _create(client, time_zone="Europe/Berlin")

        assert answer.start is not None and answer.start.iso == "2026-03-02T14:00:00+01:00"
        assert answer.end is not None and answer.end.iso == "2026-03-02T15:00:00+01:00"
        assert answer.start.local == "2026-03-02T13:00:00.0000000"
        assert answer.start.time_zone == "UTC"

    async def test_a_windows_zone_leaves_the_comparable_value_null_and_reports_graphs_own(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft accepts a Windows zone name and `zoneinfo` has no such key, so the conversion
        is what is lost and nothing else. The event itself was created in that zone."""
        _ = _ready(
            graph,
            created=_created_payload(
                start={
                    "dateTime": "2026-03-02T14:00:00.0000000",
                    "timeZone": "W. Europe Standard Time",
                }
            ),
        )

        answer = await _create(client, time_zone="W. Europe Standard Time")

        assert answer.start is not None
        assert answer.start.iso is None
        assert answer.start.time_zone == "W. Europe Standard Time"

    async def test_it_answers_the_join_link_from_the_online_meeting_and_not_the_deprecated_url(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(
            graph,
            created=_created_payload(online_meeting=True, join_url=_JOIN_URL),
        )

        answer = await _create(client, online_meeting=True)

        assert answer.is_online_meeting is True
        assert answer.join_url == _JOIN_URL

    async def test_an_event_with_no_online_meeting_answers_no_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, created=_created_payload(join_url=None))

        answer = await _create(client)

        assert answer.join_url is None

    async def test_the_subject_the_link_and_the_transaction_id_come_off_the_201(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(
            graph,
            created=_created_payload(
                subject="Pricing review (stored)", transaction_id="SYNTHETIC-transaction-0009"
            ),
        )

        answer = await _create(client)

        assert answer.subject == "Pricing review (stored)"
        assert answer.web_link == _WEB_LINK
        assert answer.transaction_id == "SYNTHETIC-transaction-0009"

    async def test_a_create_graph_echoed_no_transaction_id_for_answers_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, created=_created_payload(transaction_id=None))

        answer = await _create(client)

        assert answer.transaction_id is None

    async def test_the_location_comes_off_the_201_rather_than_the_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, created=_created_payload(location="Room 3 (Zurich)"))

        answer = await _create(client, location="Room 3")

        assert answer.location == "Room 3 (Zurich)"

    async def test_a_response_that_is_not_an_event_is_refused_rather_than_answered(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, created=_message_envelope())

        with pytest.raises(AssertionError) as raised:
            _ = await _create(client, attendees=[_ADA])

        assert "#microsoft.graph.eventMessage" in str(raised.value), (
            "the failure does not say what arrived instead"
        )
        assert "was created" in str(raised.value), (
            "the failure reads as though nothing had happened"
        )

    async def test_every_field_of_the_answer_says_what_it_is(self) -> None:
        published = CreatedEventOnBehalf.model_json_schema()

        assert "EventTime" in cast("Mapping[str, object]", published.get("$defs", {})), (
            "the walk below found no nested shape, so it checked almost nothing"
        )
        assert _undescribed(published) == []

    def test_no_recurrence_or_attachment_is_addressable_in_the_answer_at_all(self) -> None:
        fields = CreatedEventOnBehalf.model_fields
        assert not [name for name in fields if "recur" in name.casefold()]
        assert not [name for name in fields if "attach" in name.casefold()]


class TestTheSchemaItPublishes:
    async def test_the_calendar_and_the_zone_are_required_and_no_client_is_published(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        required = cast("Sequence[str]", parameters["required"])
        assert set(required) == {
            "calendar_ref",
            "subject",
            "starts_at",
            "ends_at",
            "time_zone",
            "attendees",
        }
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert "client" not in properties, "the Graph client reached the published schema"
        assert "ctx" not in properties, "the FastMCP context reached the published schema"

    async def test_it_publishes_every_argument_it_takes_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {
            "calendar_ref",
            "subject",
            "starts_at",
            "ends_at",
            "time_zone",
            "attendees",
            "optional_attendees",
            "body_html",
            "location",
            "all_day",
            "online_meeting",
        }

    @pytest.mark.parametrize(
        "word", ["recur", "repeat", "attach", "hide", "series", "cancel", "user", "mailbox"]
    )
    async def test_no_argument_offers_a_series_an_attachment_or_another_mailbox(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_both_attendee_lists_are_bounded_and_the_optional_one_defaults_to_empty(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        attendees = cast("Mapping[str, object]", properties["attendees"])
        optional = cast("Mapping[str, object]", properties["optional_attendees"])
        assert attendees["maxItems"] == MAX_ATTENDEES
        assert optional["maxItems"] == MAX_ATTENDEES
        assert optional["default"] == []

    async def test_a_location_longer_than_the_ceiling_is_refused_by_the_schema(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        parameters, tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        location = cast("Mapping[str, object]", properties["location"])
        text = next(
            branch
            for branch in cast("Sequence[Mapping[str, object]]", location["anyOf"])
            if branch.get("type") == "string"
        )
        assert text["minLength"] == 1
        assert text["maxLength"] == MAX_LOCATION_CHARACTERS
        with pytest.raises(ValidationError, match="at most"):
            _ = await tool.run(
                {
                    **creator.GRAPH_CALL_EXAMPLE,
                    "location": "x" * (MAX_LOCATION_CHARACTERS + 1),
                }
            )

        assert len(graph.calls) == 0, "an argument the schema refuses reached Graph"

    async def test_a_zone_that_writes_a_sentence_of_its_own_never_reaches_this_tool(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _parameters, tool = await _registered(transport)

        with pytest.raises(ValidationError, match="match pattern"):
            _ = await tool.run(
                {**creator.GRAPH_CALL_EXAMPLE, "time_zone": "UTC? Microsoft mails nobody"}
            )

        assert len(graph.calls) == 0, "a zone the schema refuses reached Graph"

    @pytest.mark.parametrize(
        "zone",
        ["UTC", "W. Europe Standard Time", "America/Argentina/Buenos_Aires", "Etc/GMT+2"],
        ids=["utc", "windows", "three-part-iana", "iana-with-an-offset"],
    )
    async def test_a_zone_name_either_family_spells_satisfies_the_published_shape(
        self, transport: httpx.AsyncClient, zone: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        published = cast("Mapping[str, object]", properties["time_zone"])
        assert published["maxLength"] == MAX_ZONE_CHARACTERS
        accepted: TypeAdapter[str] = TypeAdapter(
            Annotated[
                str,
                Field(
                    pattern=cast("str", published["pattern"]),
                    max_length=cast("int", published["maxLength"]),
                ),
            ]
        )

        assert accepted.validate_python(zone) == zone

    async def test_two_calls_do_not_share_one_optional_attendee_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The default is declared on the `Field` rather than in the signature, where a `[]` is
        one list for the life of the process."""
        create = _ready(graph)

        _ = await _create(client, optional_attendees=[_GRACE])
        _ = await _create(client)

        assert "attendees" not in _sent(create)

    @pytest.mark.parametrize(
        "argument", ["subject", "starts_at", "ends_at", "time_zone", "attendees"]
    )
    async def test_no_other_required_argument_names_a_tool_in_its_own_description(
        self, transport: httpx.AsyncClient, argument: str
    ) -> None:
        """test_tool_selection.py records a required argument whose prose names a tool as
        minted by it; calendar_ref names another tool too, so the check searches either prefix."""
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        described = str(cast("Mapping[str, object]", properties[argument]).get("description", ""))
        assert "outlook_" not in described, f"`{argument}` names a tool it does not need"
        assert "teams_" not in described, f"`{argument}` names a tool it does not need"

    async def test_the_calendar_argument_says_which_tool_mints_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        described = str(
            cast("Mapping[str, object]", properties["calendar_ref"]).get("description", "")
        )
        assert "outlook_list_calendars" in described


class TestHowItDeclaresItself:
    def test_the_permissions_are_the_least_privileged_ones_for_its_two_calls_in_order(
        self,
    ) -> None:
        """Microsoft's calendar-get page names Calendars.Read (no .Shared) for the pre-read; its
        delegated-create walkthrough names Calendars.Read.Shared and Calendars.ReadWrite.Shared."""
        assert creator.GRAPH_PERMISSIONS == (
            "Calendars.Read",
            "Calendars.Read.Shared",
            "Calendars.ReadWrite.Shared",
        )

    def test_its_create_step_is_the_one_the_own_calendar_create_uses(self) -> None:
        assert creator.STEP_CREATE == "create_event"

    async def test_it_announces_itself_as_a_write_that_destroys_nothing(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_the_description_says_whose_name_the_event_goes_out_under(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "as that person" in lowered
        assert "organizer" in lowered
        assert "nothing in the event" in lowered
        assert "cannot recall" in lowered

    async def test_the_description_says_a_person_is_asked_before_anything_is_created(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "confirm before it creates anything" in lowered
        assert "creates nothing unless they agree" in lowered

    async def test_the_description_sends_the_users_own_calendar_to_the_other_create(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "outlook_create_event for the user's own calendar" in description
        assert "outlook_list_calendars" in description
        assert "`can_edit`" in description

    @pytest.mark.parametrize(
        "caution",
        ["attach", "repeat", "wall-clock", "times out"],
    )
    async def test_the_description_carries_the_cautions_a_create_needs(
        self, transport: httpx.AsyncClient, caution: str
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert caution in (tool.description or "").casefold()

    def test_its_not_found_advice_sends_the_caller_back_to_the_calendar_listing(self) -> None:
        assert "outlook_list_calendars" in creator.GRAPH_NOT_FOUND
        assert "NO EVENT WAS CREATED" in creator.GRAPH_NOT_FOUND

    def test_the_example_call_reaches_graph_without_inviting_anybody(self) -> None:
        assert creator.GRAPH_CALL_EXAMPLE["attendees"] == []
        assert creator.GRAPH_CALL_EXAMPLE["calendar_ref"] == _CALENDAR_REF


class TestTheFailuresItPassesOn:
    async def test_a_refused_pre_read_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CALENDAR_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )
        create = _creates(graph)

        with pytest.raises(GraphForbidden):
            _ = await _create(client)

        assert create.call_count == 0

    async def test_a_calendar_graph_will_not_return_is_a_not_found_and_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CALENDAR_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "Not Found"}}
            )
        )
        create = _creates(graph)

        with pytest.raises(GraphNotFound):
            _ = await _create(client)

        assert create.call_count == 0

    async def test_a_refused_create_is_a_forbidden_and_is_not_retried(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A calendar that reports `canEdit` true and refuses the write anyway is Exchange
        disagreeing with Graph, and one 403 is the whole of what this tool does about it."""
        _ = _reads(graph)
        create = graph.post(_EVENTS_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _create(client)

        assert create.call_count == 1, "a refused create was retried into a duplicate meeting"
