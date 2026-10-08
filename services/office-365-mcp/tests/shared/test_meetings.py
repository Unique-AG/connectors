"""The meeting vocabulary: the `$filter` that reaches a meeting, and the window that scopes it.

`teams_list_meeting_transcripts`, `teams_list_meeting_recordings` and `teams_read_transcript` all
rest on this, so it
is tested here once rather than once per lister. Every payload is synthesised.
"""

from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest
import respx
from msgraph.generated.models.identity import Identity
from msgraph.generated.models.identity_set import IdentitySet
from msgraph.generated.models.meeting_participant_info import MeetingParticipantInfo
from msgraph.generated.models.meeting_participants import MeetingParticipants
from msgraph.generated.models.online_meeting import OnlineMeeting
from msgraph.generated.models.user import User
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.shared import handles, meetings
from office_365_mcp.shared.identity import Person

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


class TestHowLongAnAbsenceStaysUnsettled:
    """`2026-02-10` and `2026-02-10T14:00:00` both used to reach a comparison between a naive
    datetime and Graph's aware one and raise `TypeError` at the caller. Resolving happens once,
    here, so nothing downstream can meet a naive datetime."""

    def test_the_allowance_is_generous_enough_to_be_the_safe_side(self) -> None:
        """Microsoft publishes no availability SLA, and a tight window reports a still-processing
        transcript as one that will never exist — the one wrong answer a caller cannot detect."""
        assert timedelta(hours=1) <= meetings.ARTIFACT_DELAY_ALLOWANCE


_ORGANIZER_ID = "00000000-0000-4000-8000-000000000001"
_ATTENDEE_ID = "00000000-0000-4000-8000-000000000002"


def _organized_by(organizer_id: str | None) -> OnlineMeeting:
    return OnlineMeeting(
        participants=MeetingParticipants(
            organizer=MeetingParticipantInfo(identity=IdentitySet(user=Identity(id=organizer_id))),
            attendees=[
                MeetingParticipantInfo(identity=IdentitySet(user=Identity(id=_ATTENDEE_ID)))
            ],
        )
    )


class TestWhoOrganizesTheMeeting:
    def test_the_organizer_is_the_signed_in_user(self) -> None:
        assert meetings.organized_by(_organized_by(_ORGANIZER_ID), User(id=_ORGANIZER_ID))

    def test_an_attendee_is_not_the_organizer(self) -> None:
        assert not meetings.organized_by(_organized_by(_ORGANIZER_ID), User(id=_ATTENDEE_ID))

    def test_the_ids_compare_without_case(self) -> None:
        assert meetings.organized_by(_organized_by(_ORGANIZER_ID.upper()), User(id=_ORGANIZER_ID))

    @pytest.mark.parametrize(
        "meeting",
        [
            pytest.param(OnlineMeeting(), id="no-participants"),
            pytest.param(OnlineMeeting(participants=MeetingParticipants()), id="no-organizer"),
            pytest.param(
                OnlineMeeting(participants=MeetingParticipants(organizer=MeetingParticipantInfo())),
                id="no-identity",
            ),
            pytest.param(
                OnlineMeeting(
                    participants=MeetingParticipants(
                        organizer=MeetingParticipantInfo(identity=IdentitySet())
                    )
                ),
                id="no-user",
            ),
            pytest.param(_organized_by(None), id="no-id"),
        ],
    )
    def test_a_meeting_that_names_no_organizer_is_not_organized_by_the_user(
        self, meeting: OnlineMeeting
    ) -> None:
        assert not meetings.organized_by(meeting, User(id=_ORGANIZER_ID))

    def test_a_user_with_no_id_organizes_nothing(self) -> None:
        assert not meetings.organized_by(_organized_by(_ORGANIZER_ID), User())


_TOOL = "teams_example_meeting_tool"
_TAIL = "No meeting was changed. The call will fail the same way."
_STARTS_AT = "2026-03-02T14:00:00+01:00"


class TestTheMeetingTimes:
    def test_two_times_with_an_offset_are_two_instants(self) -> None:
        times = meetings.meeting_times(_TOOL, _STARTS_AT, "2026-03-02T15:00:00Z", tail=_TAIL)

        assert times == (
            datetime(2026, 3, 2, 14, tzinfo=timezone(timedelta(hours=1))),
            datetime(2026, 3, 2, 15, tzinfo=UTC),
        )

    @pytest.mark.parametrize(
        ("starts_at", "ends_at", "argument"),
        [
            pytest.param("2026-03-02T14:00:00", "2026-03-02T15:00:00Z", "starts_at", id="start"),
            pytest.param(_STARTS_AT, "2026-03-02", "ends_at", id="end"),
        ],
    )
    def test_a_time_with_no_offset_is_refused_by_its_argument(
        self, starts_at: str, ends_at: str, argument: str
    ) -> None:
        refused = meetings.meeting_times(_TOOL, starts_at, ends_at, tail=_TAIL)

        assert isinstance(refused, str)
        assert refused.startswith(f"{_TOOL} received ")
        assert f"`{argument}`. This time has no offset" in refused
        assert "or add `Z` for UTC." in refused
        assert refused.endswith(_TAIL)

    @pytest.mark.parametrize("starts_at", ["tomorrow at 2", "1772719200", "02/03/2026 14:00"])
    def test_a_value_that_is_not_iso_8601_is_refused(self, starts_at: str) -> None:
        refused = meetings.meeting_times(_TOOL, starts_at, "2026-03-02T15:00:00Z", tail=_TAIL)

        assert isinstance(refused, str)
        assert f"{_TOOL} received {starts_at!r} in `starts_at`." in refused
        assert "This value is not an ISO-8601 date and time." in refused
        assert "Calculate the date and the time from what the user said." in refused
        assert refused.endswith(_TAIL)

    @pytest.mark.parametrize("ends_at", [_STARTS_AT, "2026-03-02T12:59:00Z"])
    def test_an_end_that_is_not_after_the_start_is_refused(self, ends_at: str) -> None:
        refused = meetings.meeting_times(_TOOL, _STARTS_AT, ends_at, tail=_TAIL)

        assert isinstance(refused, str)
        assert f"{_TOOL} received an `ends_at` that is not after `starts_at`." in refused
        assert "A meeting that runs past midnight ends on the next day." in refused
        assert refused.endswith(_TAIL)


_OTHER_ATTENDEE_ID = "00000000-0000-4000-8000-000000000003"


class TestTheAttendees:
    def test_each_id_becomes_one_attendee_and_none_becomes_the_organizer(self) -> None:
        participants = meetings.meeting_participants([_ATTENDEE_ID, _OTHER_ATTENDEE_ID])

        assert participants.organizer is None
        assert meetings.attendee_ids(participants) == [_ATTENDEE_ID, _OTHER_ATTENDEE_ID]

    def test_no_id_becomes_an_empty_attendee_list_and_not_a_missing_one(self) -> None:
        assert meetings.meeting_participants([]).attendees == []

    def test_the_ids_come_from_the_attendees_and_leave_the_organizer_out(self) -> None:
        assert meetings.attendee_ids(_organized_by(_ORGANIZER_ID).participants) == [_ATTENDEE_ID]

    def test_an_attendee_that_names_no_user_id_is_left_out(self) -> None:
        participants = MeetingParticipants(
            attendees=[
                MeetingParticipantInfo(),
                MeetingParticipantInfo(identity=IdentitySet()),
                MeetingParticipantInfo(identity=IdentitySet(user=Identity())),
                MeetingParticipantInfo(identity=IdentitySet(user=Identity(id=_ATTENDEE_ID))),
            ]
        )

        assert meetings.attendee_ids(participants) == [_ATTENDEE_ID]

    @pytest.mark.parametrize(
        "participants",
        [
            pytest.param(None, id="no-participants"),
            pytest.param(MeetingParticipants(), id="no-attendee-list"),
        ],
    )
    def test_no_attendee_list_is_none(self, participants: MeetingParticipants | None) -> None:
        assert meetings.attendee_ids(participants) is None

    def test_an_empty_attendee_list_is_an_empty_list(self) -> None:
        assert meetings.attendee_ids(MeetingParticipants(attendees=[])) == []


class TestThePeopleTheUserNames:
    def test_each_person_appears_once_by_id_sorted_and_in_lowercase(self) -> None:
        people = meetings.distinct_people(
            [
                Person(user_id=_OTHER_ATTENDEE_ID, name="Grace"),
                Person(user_id=_ATTENDEE_ID.upper(), name="Ada"),
                Person(user_id=_ATTENDEE_ID, name="Ada Lovelace"),
            ]
        )

        assert people == (
            Person(user_id=_ATTENDEE_ID, name="Ada"),
            Person(user_id=_OTHER_ATTENDEE_ID, name="Grace"),
        )

    def test_no_person_is_no_person(self) -> None:
        assert meetings.distinct_people([]) == ()

    def test_the_question_counts_the_people_and_shows_each_object_id_with_its_label(
        self,
    ) -> None:
        named = meetings.named_people(
            [
                Person(user_id=_ATTENDEE_ID, name="Ada"),
                Person(user_id=_OTHER_ATTENDEE_ID, name="Bob"),
            ]
        )

        assert named == (
            "2 people: the person with the Microsoft Entra object id "
            + "'00000000-0000-4000-8000-000000000002' (the name 'Ada' is only a label from the "
            + "request), the person with the Microsoft Entra object id "
            + "'00000000-0000-4000-8000-000000000003' (the name 'Bob' is only a label from the "
            + "request)"
        )

    def test_one_person_is_counted_once_and_shown_by_the_object_id(self) -> None:
        named = meetings.named_people([Person(user_id=_ATTENDEE_ID, name="Ada")])

        assert named.startswith("1 person: the person with the Microsoft Entra object id ")
        assert _ATTENDEE_ID in named
        assert "'Ada' is only a label from the request" in named

    def test_a_name_of_another_person_still_shows_the_object_id_that_graph_binds(self) -> None:
        named = meetings.named_people([Person(user_id=_OTHER_ATTENDEE_ID, name="Ada Lovelace")])

        assert _OTHER_ATTENDEE_ID in named
        assert "'Ada Lovelace' is only a label from the request" in named

    def test_a_long_name_is_cut_for_the_question_and_the_object_id_is_kept(self) -> None:
        named = meetings.named_people([Person(user_id=_ATTENDEE_ID, name="A" * 500)])

        assert "A" * 500 not in named
        assert "…' is only a label from the request" in named
        assert _ATTENDEE_ID in named


class TestTheMeetingRefusals:
    def test_the_handle_refusal_names_both_sources_and_the_one_shape(self) -> None:
        refused = meetings.not_a_meeting_handle(_TOOL, tail=_TAIL)

        assert refused.startswith(
            f"{_TOOL} takes the `meeting_uri` handle from teams_list_chats or "
            + "teams_create_meeting, and this value is not one."
        )
        assert "\n  teams:///meetings/{join_web_url}\n" in refused
        assert "A `teams:///transcripts/...` handle is not a meeting handle." in refused
        assert "Copy the `meeting_uri` of a tool result word for word." in refused
        assert refused.endswith(_TAIL)

    def test_the_organizer_refusal_says_what_the_tool_does_only_for_the_organizer(self) -> None:
        refused = meetings.not_the_organizer("changes", tail=_TAIL)

        assert refused.startswith(
            "Microsoft 365 does not name the signed-in user as the organizer of this meeting."
        )
        assert "This tool changes only a meeting that the signed-in user organizes." in refused
        assert refused.endswith(_TAIL)
