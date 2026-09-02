"""Every response body here is synthesised. None came from a real mailbox."""

from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared import identity
from office_365_mcp.shared.calendar import SUMMARY_FIELDS
from office_365_mcp.shared.handles import (
    CalendarHandle,
    EventHandle,
    MailDraftHandle,
    MailFolderHandle,
    MailMessageHandle,
)
from office_365_mcp.tools import outlook_read_event as reader

from .conftest import ME

_CALENDAR_ID = "AAMkSYNTHETIC-cal-0001="
_EVENT_ID = "AAMkAGI2SYNTHETIC-immutable-0001="

# The SDK re-encodes both ids for the URL, so this is what the decoded handle comes back as.
_PATH = "/me/calendars/AAMkSYNTHETIC-cal-0001%3D/events/AAMkAGI2SYNTHETIC-immutable-0001%3D"

_HANDLE = EventHandle(_CALENDAR_ID, _EVENT_ID)

# Written out rather than joined from the module's own constants: a drift in either list is a
# different projection on the wire, and a test that recomputes it cannot see that.
_SELECTED = (
    "id,subject,bodyPreview,start,end,isAllDay,isCancelled,type,seriesMasterId,sensitivity,"
    + "showAs,location,isOnlineMeeting,onlineMeeting,organizer,isOrganizer,responseStatus,"
    + "attendees,webLink,body,hasAttachments,responseRequested,allowNewTimeProposals,"
    + "hideAttendees,originalStartTimeZone,originalEndTimeZone"
)

# Graph fills this year in `responseStatus.time` when nobody answered yet.
_NEVER_ANSWERED = "0001-01-01T00:00:00Z"


def _body(content: str, *, content_type: str = "text") -> dict[str, object]:
    return {"contentType": content_type, "content": content}


def _attendee(
    *,
    name: str = "Ada Lovelace",
    address: str = "ada@example.invalid",
    kind: str = "required",
    response: str = "accepted",
    responded_at: str = "2026-03-02T08:41:07Z",
) -> dict[str, object]:
    return {
        "type": kind,
        "status": {"response": response, "time": responded_at},
        "emailAddress": {"name": name, "address": address},
    }


def _payload(
    *,
    body: dict[str, object] | None = None,
    attendees: Sequence[Mapping[str, object]] = (),
    has_attachments: bool | None = True,
    response_requested: bool | None = True,
    allow_new_time_proposals: bool | None = True,
    hide_attendees: bool | None = False,
    original_start_zone: str | None = "W. Europe Standard Time",
    original_end_zone: str | None = "W. Europe Standard Time",
) -> dict[str, object]:
    return {
        "id": _EVENT_ID,
        "subject": "Pricing review",
        "bodyPreview": "Microsoft Teams meeting Join on your computer or mobile app",
        "start": {"dateTime": "2026-03-04T13:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-03-04T14:00:00.0000000", "timeZone": "UTC"},
        "isAllDay": False,
        "isCancelled": False,
        "type": "occurrence",
        "seriesMasterId": "AAMkSYNTHETIC-series-0001=",
        "sensitivity": "normal",
        "showAs": "busy",
        "location": {"displayName": "Conf Room Synthetic"},
        "isOnlineMeeting": True,
        "onlineMeeting": {"joinUrl": "https://teams.microsoft.invalid/l/meetup-join/SYNTHETIC"},
        "organizer": {"emailAddress": {"name": "Bob Vance", "address": "bob@vance.invalid"}},
        "isOrganizer": False,
        "responseStatus": {"response": "tentativelyAccepted", "time": "2026-03-01T10:00:00Z"},
        "attendees": [dict(attendee) for attendee in attendees],
        "webLink": "https://outlook.office365.invalid/owa/?itemid=synthetic",
        "body": body,
        "hasAttachments": has_attachments,
        "responseRequested": response_requested,
        "allowNewTimeProposals": allow_new_time_proposals,
        "hideAttendees": hide_attendees,
        "originalStartTimeZone": original_start_zone,
        "originalEndTimeZone": original_end_zone,
    }


def _reads(graph: respx.MockRouter, payload: dict[str, object]) -> respx.Route:
    return graph.get(_PATH).mock(return_value=httpx.Response(200, json=payload))


async def _read(client: GraphServiceClient, **overrides: str) -> reader.CalendarEvent:
    return await reader.read_event(client, uri=_HANDLE.uri, **overrides)


class TestWhatItAsksGraphFor:
    async def test_it_addresses_the_event_inside_the_calendar_the_handle_names(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft states that an event id from one mailbox does not resolve in another, and
        Graph puts no calendar id on an event row, so both halves of the handle are the address."""
        route = _reads(graph, _payload(body=_body("Agenda attached.")))

        _ = await _read(client)

        # `url.path` decodes, so the encoding is read off the raw path the SDK put on the wire.
        sent, _query = route.calls.last.request.url.raw_path.decode().split("?", 1)
        assert sent == f"/v1.0{_PATH}", "both ids are percent-encoded, each as one path segment"
        assert route.call_count == 1, "one event, one request"

    async def test_it_selects_the_listing_fields_and_the_seven_a_full_read_adds(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph returns none of these on a projection that does not name them."""
        route = _reads(graph, _payload(body=_body("Agenda attached.")))

        _ = await _read(client)

        assert route.calls.last.request.url.params["$select"] == _SELECTED

    async def test_every_field_a_listing_row_reads_is_selected_here_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The answer extends the listing row, so a summary field left out here is a field the
        shared shape promises and this tool answers null for."""
        route = _reads(graph, _payload(body=_body("Agenda attached.")))

        _ = await _read(client)

        selected = route.calls.last.request.url.params["$select"].split(",")
        assert [field for field in SUMMARY_FIELDS if field not in selected] == []

    async def test_it_never_asks_for_an_attachment_or_the_recurrence_rule(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Not asking is the whole of the control: there is no filter downstream of `$select`."""
        route = _reads(graph, _payload(body=_body("Agenda attached.")))

        _ = await _read(client)

        selected = route.calls.last.request.url.params["$select"]
        assert "attachments" not in selected
        assert "recurrence" not in selected

    async def test_it_prefers_a_text_body_and_declares_the_immutable_id_space(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft documents `Prefer: outlook.body-content-type` on this operation. The id-space
        preference keeps one id space across the whole surface instead of two."""
        route = _reads(graph, _payload(body=_body("Agenda attached.")))

        _ = await _read(client)

        preferences = route.calls.last.request.headers["prefer"]
        assert 'outlook.body-content-type="text"' in preferences
        assert 'IdType="ImmutableId"' in preferences

    async def test_it_never_asks_graph_to_render_the_times_in_a_zone(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`Prefer: outlook.timezone` moves the conversion into Exchange and silently drops the
        zone the event was created in. This connector converts with `zoneinfo` instead."""
        route = _reads(graph, _payload(body=_body("Agenda attached.")))

        _ = await _read(client, time_zone="Europe/Zurich")

        assert "outlook.timezone" not in route.calls.last.request.headers["prefer"]

    async def test_it_never_asks_graph_to_stop_sanitizing_the_html(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _reads(graph, _payload(body=_body("Agenda attached.")))

        _ = await _read(client)

        assert "allow-unsafe-html" not in route.calls.last.request.headers["prefer"]

    async def test_the_preferences_are_not_added_to_every_other_graph_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """kiota's `RequestConfiguration.headers` defaults to one `HeadersCollection` shared by
        every configuration in the process, so a header added to the default leaks everywhere.

        `shared/identity.py`'s `GET /me` is the witness because it passes a `RequestConfiguration`
        of its own; a call passing none would keep passing while the leak came back.
        """
        _ = _reads(graph, _payload(body=_body("Agenda attached.")))
        profile = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))

        _ = await _read(client)
        _ = await identity.signed_in_user(client)

        assert "prefer" not in profile.calls.last.request.headers


class TestWhetherGraphConvertedTheBody:
    async def test_a_body_graph_reported_as_text_is_labelled_plain_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload(body=_body("Agenda attached.", content_type="text")))

        answer = await _read(client)

        assert answer.body == "Agenda attached."
        assert answer.body_is_plain_text is True

    async def test_a_body_graph_left_as_html_is_not_labelled_plain_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The documented preference and the documented behaviour of this operation disagree, so
        the response decides and the request never does."""
        _ = _reads(graph, _payload(body=_body("<p>Agenda attached.</p>", content_type="html")))

        answer = await _read(client)

        assert answer.body_is_plain_text is False

    async def test_the_markup_reaches_the_caller_exactly_as_graph_sent_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """No stripper of our own: one would turn a script block into sentences that read as prose
        the organizer wrote."""
        markup = '<div><script>alert("join here")</script><p>Agenda.</p></div>'
        _ = _reads(graph, _payload(body=_body(markup, content_type="html")))

        answer = await _read(client)

        assert answer.body == markup

    async def test_an_event_with_no_body_answers_null_and_no_length(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload())

        answer = await _read(client)

        assert answer.body is None
        assert answer.body_characters == 0
        assert answer.body_truncated is False
        assert answer.body_is_plain_text is False

    async def test_a_body_of_nothing_but_whitespace_answers_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload(body=_body("   \n  ")))

        answer = await _read(client)

        assert answer.body is None
        assert answer.body_characters == 0


class TestTheCapOnTheBody:
    async def test_a_body_over_the_cap_keeps_the_head_and_says_it_was_cut(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        content = "A" * reader.MAX_BODY_CHARACTERS + "TAIL"
        _ = _reads(graph, _payload(body=_body(content)))

        answer = await _read(client)

        assert answer.body == "A" * reader.MAX_BODY_CHARACTERS
        assert answer.body_truncated is True

    async def test_it_reports_the_length_the_body_had_before_truncation(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        content = "A" * (reader.MAX_BODY_CHARACTERS + 4)
        _ = _reads(graph, _payload(body=_body(content)))

        answer = await _read(client)

        assert answer.body_characters == reader.MAX_BODY_CHARACTERS + 4

    async def test_a_body_exactly_at_the_cap_is_whole(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        content = "A" * reader.MAX_BODY_CHARACTERS
        _ = _reads(graph, _payload(body=_body(content)))

        answer = await _read(client)

        assert answer.body == content
        assert answer.body_truncated is False
        assert answer.body_characters == reader.MAX_BODY_CHARACTERS


class TestTheAttendeesItReports:
    async def test_each_attendee_carries_a_kind_a_response_and_a_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft documents `status` as "the attendee's response … and date-time that the
        response was sent" (https://learn.microsoft.com/en-us/graph/api/resources/attendee)."""
        _ = _reads(graph, _payload(body=_body("Agenda."), attendees=[_attendee()]))

        answer = await _read(client)

        assert len(answer.attendees) == 1
        invited = answer.attendees[0]
        assert invited.name == "Ada Lovelace"
        assert invited.address == "ada@example.invalid"
        assert invited.kind == "required"
        assert invited.response == "accepted"
        assert invited.responded_at is not None
        assert invited.responded_at.startswith("2026-03-02T08:41:07")

    async def test_an_attendee_who_never_answered_reports_no_time_at_all(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph fills the year 1 rather than a null, and reporting it as a timestamp reads as a
        response from before the calendar existed."""
        _ = _reads(
            graph,
            _payload(
                body=_body("Agenda."),
                attendees=[_attendee(response="none", responded_at=_NEVER_ANSWERED)],
            ),
        )

        answer = await _read(client)

        assert answer.attendees[0].response == "none"
        assert answer.attendees[0].responded_at is None

    async def test_a_room_exchange_added_is_reported_as_a_resource(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Exchange adds a resource attendee of its own when a location matches a bookable room,
        so a room appears here that nobody typed."""
        _ = _reads(
            graph,
            _payload(
                body=_body("Agenda."),
                attendees=[
                    _attendee(),
                    _attendee(
                        name="Conf Room Synthetic",
                        address="room@example.invalid",
                        kind="resource",
                        response="organizer",
                    ),
                ],
            ),
        )

        answer = await _read(client)

        assert [invited.kind for invited in answer.attendees] == ["required", "resource"]

    async def test_the_owners_own_response_is_not_confused_with_an_attendees(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`responseStatus` is the answer of whoever owns the calendar the row was read from, and
        on a delegated calendar that is not the signed-in user."""
        _ = _reads(graph, _payload(body=_body("Agenda."), attendees=[_attendee()]))

        answer = await _read(client)

        assert answer.owner_response == "tentativelyAccepted"
        assert answer.attendees[0].response == "accepted"

    async def test_an_event_nobody_was_invited_to_reports_an_empty_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload(body=_body("Block this out.")))

        answer = await _read(client)

        assert answer.attendees == []
        assert answer.attendee_count == 0


class TestWhatItAnswers:
    async def test_it_carries_the_handle_the_caller_addressed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload(body=_body("Agenda.")))

        answer = await _read(client)

        assert answer.uri == _HANDLE.uri

    async def test_the_times_are_converted_into_the_zone_that_was_asked_for(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Without `Prefer: outlook.timezone` Graph renders both bounds in UTC, and 13:00 UTC in
        March is 14:00 in Zurich."""
        _ = _reads(graph, _payload(body=_body("Agenda.")))

        answer = await _read(client, time_zone="Europe/Zurich")

        assert answer.start is not None
        assert answer.start.iso == "2026-03-04T14:00:00+01:00"
        assert answer.end is not None
        assert answer.end.iso == "2026-03-04T15:00:00+01:00"

    async def test_graphs_own_two_values_survive_the_conversion(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload(body=_body("Agenda.")))

        answer = await _read(client, time_zone="Europe/Zurich")

        assert answer.start is not None
        assert answer.start.local == "2026-03-04T13:00:00.0000000"
        assert answer.start.time_zone == "UTC"

    async def test_the_default_zone_reads_the_event_in_utc(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload(body=_body("Agenda.")))

        answer = await _read(client)

        assert answer.start is not None
        assert answer.start.iso == "2026-03-04T13:00:00+00:00"

    async def test_it_reports_the_zones_the_event_was_created_in(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """These are Windows names as often as IANA ones, and they say where the organizer was."""
        _ = _reads(graph, _payload(body=_body("Agenda.")))

        answer = await _read(client)

        assert answer.original_start_time_zone == "W. Europe Standard Time"
        assert answer.original_end_time_zone == "W. Europe Standard Time"

    async def test_it_reports_what_the_organizer_asked_for_and_allowed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            _payload(
                body=_body("Agenda."),
                response_requested=False,
                allow_new_time_proposals=False,
                hide_attendees=True,
            ),
        )

        answer = await _read(client)

        assert answer.response_requested is False
        assert answer.allow_new_time_proposals is False
        assert answer.hide_attendees is True

    async def test_an_attachment_is_a_boolean_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload(body=_body("Agenda.")))

        answer = await _read(client)

        assert answer.has_attachments is True
        named = [name for name in reader.CalendarEvent.model_fields if "attachment" in name]
        assert named == ["has_attachments"], "no field here carries an attachment's contents"

    async def test_a_property_graph_left_out_is_reported_as_unknown_rather_than_false(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            _payload(
                body=_body("Agenda."),
                has_attachments=None,
                response_requested=None,
                allow_new_time_proposals=None,
                hide_attendees=None,
                original_start_zone=None,
                original_end_zone=None,
            ),
        )

        answer = await _read(client)

        assert answer.has_attachments is None
        assert answer.response_requested is None
        assert answer.allow_new_time_proposals is None
        assert answer.hide_attendees is None
        assert answer.original_start_time_zone is None
        assert answer.original_end_time_zone is None

    async def test_it_still_reports_everything_a_listing_row_already_carried(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _payload(body=_body("Agenda."), attendees=[_attendee()]))

        answer = await _read(client)

        assert answer.subject == "Pricing review"
        assert answer.preview is not None
        assert answer.all_day is False
        assert answer.cancelled is False
        assert answer.kind == "occurrence"
        assert answer.in_series is True
        assert answer.sensitivity == "normal"
        assert answer.show_as == "busy"
        assert answer.location == "Conf Room Synthetic"
        assert answer.is_online_meeting is True
        assert answer.join_url == "https://teams.microsoft.invalid/l/meetup-join/SYNTHETIC"
        assert answer.organizer is not None
        assert answer.organizer.address == "bob@vance.invalid"
        assert answer.is_organizer is False
        assert answer.attendee_count == 1
        assert answer.web_link == "https://outlook.office365.invalid/owa/?itemid=synthetic"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "uri",
        [
            CalendarHandle(_CALENDAR_ID).uri,
            MailMessageHandle(_EVENT_ID).uri,
            MailDraftHandle("AAMkAGI2SYNTHETIC-draft-0001=").uri,
            MailFolderHandle("AQMkADAwSYNTHETIC-folder").uri,
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
            f"outlook:///events/{_EVENT_ID}",
            "AAMkAGI2SYNTHETIC-immutable-0001=",
            "https://outlook.office365.invalid/owa/?itemid=synthetic",
            "Pricing review",
        ],
    )
    async def test_a_uri_that_is_not_an_event_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, uri: str
    ) -> None:
        """A calendar handle names the container and not an event in it, a mail handle addresses
        another surface, and a bare event id addresses nothing without its calendar."""
        route = _reads(graph, _payload(body=_body("Agenda.")))

        with pytest.raises(ToolError, match="outlook_list_events"):
            _ = await reader.read_event(client, uri=uri)

        assert route.call_count == 0, "the refusal has to land before the request"

    @pytest.mark.parametrize(
        "time_zone",
        ["W. Europe Standard Time", "+02:00", "CEST", "PST", "Europe/Nowhere", "", "/etc/UTC"],
    )
    async def test_a_zone_name_the_time_zone_database_lacks_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, time_zone: str
    ) -> None:
        """An unknown name reaches `zone_named` as a lookup failure, and a name that is not a
        relative path, such as an empty string, reaches it as a `ValueError` instead. A Windows
        name is the one a model reads off a previous answer, because Graph returns those.

        `CEST` and `PST` are refused where `CET` and `EST` resolve: the tz database carries a few
        legacy abbreviation-shaped keys and no daylight ones, so this is not a rule about shape.
        """
        route = _reads(graph, _payload(body=_body("Agenda.")))

        with pytest.raises(ToolError, match="IANA"):
            _ = await _read(client, time_zone=time_zone)

        assert route.call_count == 0, "the refusal has to land before the request"

    async def test_the_handle_refusal_names_the_one_shape_and_who_mints_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _reads(graph, _payload(body=_body("Agenda.")))

        with pytest.raises(ToolError) as refused:
            _ = await reader.read_event(client, uri=CalendarHandle(_CALENDAR_ID).uri)

        text = str(refused.value)
        assert "outlook:///events/{calendar_id}/{event_id}" in text
        assert "outlook_list_events" in text
        assert "Retrying this value will fail identically." in text
        assert route.call_count == 0, "the refusal has to land before the request"

    async def test_the_zone_refusal_shows_an_iana_name_and_says_nothing_was_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _reads(graph, _payload(body=_body("Agenda.")))

        with pytest.raises(ToolError) as refused:
            _ = await _read(client, time_zone="W. Europe Standard Time")

        text = str(refused.value)
        assert "Europe/Zurich" in text
        assert "Nothing was read." in text
        assert "Retrying this value will fail identically." in text
        assert route.call_count == 0, "the refusal has to land before the request"


class TestTheSchemaItPublishes:
    async def test_the_handle_is_the_only_required_argument(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters = await _registered(transport)

        assert cast("Sequence[str]", parameters["required"]) == ["uri"]

    async def test_the_zone_defaults_to_utc(self, transport: httpx.AsyncClient) -> None:
        """A default of the user's own zone is not available: this tool reads no mailbox
        settings."""
        parameters = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        time_zone = cast("Mapping[str, object]", properties["time_zone"])
        assert time_zone["default"] == "UTC"

    async def test_it_takes_two_arguments_and_no_others(self, transport: httpx.AsyncClient) -> None:
        """Neither `client` nor a context reaches the wire."""
        parameters = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"uri", "time_zone"}

    @pytest.mark.parametrize("word", ["attach", "recurrence", "accept", "decline", "cancel"])
    async def test_no_argument_offers_an_attachment_or_an_answer_to_the_invitation(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        """The absence of the argument is the control: a published argument is an invitation the
        model takes."""
        parameters = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        """Asserted over the published schema rather than the model class: a description that
        never reaches the wire is not one."""
        mcp: FastMCP = FastMCP(name="schema-under-test")
        reader.register(mcp, transport)
        tool = await mcp.get_tool(reader.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"
        published = tool.output_schema
        assert published is not None, "the answer reaches a model with no schema at all"

        fields = _fields(published)

        # Guards the guard: a walk that stopped at the top level would pass by finding little.
        assert "EventAttendee.responded_at" in fields
        assert "EventTime.iso" in fields
        undescribed = sorted(
            path for path, field in fields.items() if not _mapping(field).get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"


class TestHowItDeclaresItself:
    def test_the_permissions_are_the_ones_microsoft_documents(self) -> None:
        """Both are needed and in this order: reading an event on a calendar another person shared
        is the `.Shared` permission, and a refusal names them as the tool declares them."""
        assert reader.GRAPH_PERMISSIONS == ("Calendars.Read", "Calendars.Read.Shared")

    def test_the_step_is_one_name_for_the_one_request_it_makes(self) -> None:
        assert reader.STEP == "calendar_event"

    def test_the_refusable_call_is_one_this_tool_accepts(self) -> None:
        """An argument the tool rejects never reaches Graph, so it proves nothing about a 403."""
        assert set(reader.GRAPH_CALL_EXAMPLE) == {"uri"}
        assert reader.GRAPH_CALL_EXAMPLE["uri"] == EventHandle(_CALENDAR_ID, _EVENT_ID).uri

    async def test_it_announces_itself_as_reading_and_writing_nothing(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        reader.register(mcp, transport)

        tool = await mcp.get_tool(reader.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True


class TestTheFailuresItPassesOn:
    async def test_an_event_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph answers 'deleted', 'moved to another calendar', 'never existed' and 'you may not
        see it' identically."""
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _read(client)

    async def test_a_refused_read_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _read(client)

    def test_a_404_is_answered_with_the_recovery_and_not_with_a_canceled_meeting(self) -> None:
        """The default 404 advice says to check the id came from a tool response verbatim. This
        handle already did, so the advice a model needs is to list the window again."""
        assert "outlook_list_events" in reader.GRAPH_NOT_FOUND
        assert "never that the meeting was canceled" in reader.GRAPH_NOT_FOUND
        assert "this is not a bad argument" in reader.GRAPH_NOT_FOUND


async def _registered(transport: httpx.AsyncClient) -> Mapping[str, object]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    reader.register(mcp, transport)
    tool = await mcp.get_tool(reader.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool.parameters


def _fields(schema: Mapping[str, object], *, path: str = "") -> dict[str, object]:
    """Every field of the published output schema, named by its path.

    `$defs` is walked because pydantic publishes a nested model once and references it: a nested
    field with nothing to say about it is invisible to a walk that stops at `properties`.
    """
    found = {f"{path}{name}": field for name, field in _mapping(schema.get("properties")).items()}
    for name, defined in _mapping(schema.get("$defs")).items():
        found.update(_fields(_mapping(defined), path=f"{name}."))
    return found


def _mapping(value: object) -> Mapping[str, object]:
    """One node of a JSON schema, or an empty mapping for a key the schema does not carry."""
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else {}
