"""Reaching a Teams meeting from the conversation side, and reading its artifacts.

Of the three documented ways to reach an `onlineMeeting`
(https://learn.microsoft.com/en-us/graph/api/onlinemeeting-get), only `joinWebUrl` works from a
chat, and the sole delegated source of one is `chat.onlineMeetingInfo.joinWebUrl`, which can be
null. `chatInfo.threadId` filters in practice and appears in no Microsoft document, so this takes
the documented route instead. Neither artifact collection names a date Microsoft 365 will filter
on, so no tool here offers a date bound.

TRAP: Graph asks for a URL-encoded `joinWebUrl`, but the SDK already escapes the query value, so
encoding it here too sends `%2525…` and Graph answers `200 OK` with an empty `value` — its
documented "no match", indistinguishable from "no such meeting". Only the OData literal escape
(doubled single quotes) belongs here, and the tests pin the exact bytes on the wire.

Every artifact API stops working once the meeting expires, roughly 60 days after a one-off
(https://learn.microsoft.com/en-us/microsoftteams/limits-specifications-teams#meeting-expiration).
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.identity import Identity
from msgraph.generated.models.identity_set import IdentitySet
from msgraph.generated.models.meeting_participant_info import MeetingParticipantInfo
from msgraph.generated.models.meeting_participants import MeetingParticipants
from msgraph.generated.models.online_meeting import OnlineMeeting
from msgraph.generated.models.user import User
from msgraph.generated.users.item.online_meetings.online_meetings_request_builder import (
    OnlineMeetingsRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import CollectedItems, GraphCollection, collect_pages, graph_step
from office_365_mcp.shared.handles import MeetingHandle
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.window import as_utc

# This is the least-privileged permission for the resolve filter, and it needs no admin consent.
MEETING_PERMISSION = "OnlineMeetings.Read"

STEP_RESOLVE_MEETING = "resolve_meeting"

# Both need admin consent. Spelled once here because a second spelling of either name is a scope
# Entra rejects, which fails sign-in for everybody.
TRANSCRIPT_PERMISSION = "OnlineMeetingTranscript.Read.All"
RECORDING_PERMISSION = "OnlineMeetingRecording.Read.All"

# Graph chooses the page size, so one listing is bounded by artifacts and not by requests.
MAX_ARTIFACT_SCAN = 200

# How long after a meeting ends a missing artifact still counts as "not ready" rather than "never
# made". Microsoft publishes no SLA and no "processing" status, so this is generous on purpose.
ARTIFACT_DELAY_ALLOWANCE = timedelta(hours=4)

type _MeetingsQuery = OnlineMeetingsRequestBuilder.OnlineMeetingsRequestBuilderGetQueryParameters


class MeetingArtifact(Protocol):
    """Structural and not nominal, because `callTranscript` and `callRecording` are unrelated
    generated classes."""

    @property
    def id(self) -> str | None: ...

    @property
    def created_date_time(self) -> datetime | None: ...


def settled(meeting: OnlineMeeting) -> bool:
    """Whether an empty artifact listing means "there is none" rather than "not yet", read off the
    meeting's own end alone."""
    return _settled_by(meeting.end_date_time, datetime.now(UTC))


async def resolve_meeting(
    client: GraphServiceClient, handle: MeetingHandle
) -> OnlineMeeting | None:
    """The meeting whose `joinWebUrl` is the handle's, or None if Graph matched none. `200 OK` with
    an empty value is "no match", not a 404."""
    escaped = odata_literal(handle.join_web_url)
    configuration = RequestConfiguration[_MeetingsQuery](
        query_parameters=OnlineMeetingsRequestBuilder.OnlineMeetingsRequestBuilderGetQueryParameters(
            filter=f"JoinWebUrl eq '{escaped}'"
        )
    )
    with graph_step(STEP_RESOLVE_MEETING):
        matched = await client.me.online_meetings.get(request_configuration=configuration)
    assert matched is not None, "Graph answered GET /me/onlineMeetings with no collection"
    meetings = matched.value or []
    return meetings[0] if meetings else None


def organized_by(meeting: OnlineMeeting, user: User) -> bool:
    participants = meeting.participants
    organizer = None if participants is None else participants.organizer
    identities = None if organizer is None else organizer.identity
    named = None if identities is None or identities.user is None else identities.user.id
    return named is not None and user.id is not None and named.casefold() == user.id.casefold()


def meeting_times(
    tool: str, starts_at: str, ends_at: str, *, tail: str
) -> tuple[datetime, datetime] | str:
    opens = _instant(tool, "starts_at", starts_at, tail=tail)
    if isinstance(opens, str):
        return opens
    closes = _instant(tool, "ends_at", ends_at, tail=tail)
    if isinstance(closes, str):
        return closes
    if closes <= opens:
        return (
            f"{tool} received an `ends_at` that is not after `starts_at`. A meeting must end "
            + "after it starts. A meeting that runs past midnight ends on the next day. Make sure "
            + f"that the date of `ends_at` is correct. {tail}"
        )
    return opens, closes


def meeting_participants(attendees: Sequence[str]) -> MeetingParticipants:
    return MeetingParticipants(
        attendees=[
            MeetingParticipantInfo(identity=IdentitySet(user=Identity(id=attendee)))
            for attendee in attendees
        ]
    )


def attendee_ids(participants: MeetingParticipants | None) -> list[str] | None:
    attendees = None if participants is None else participants.attendees
    if attendees is None:
        return None
    return [
        attendee.identity.user.id
        for attendee in attendees
        if attendee.identity is not None
        and attendee.identity.user is not None
        and attendee.identity.user.id is not None
    ]


def not_a_meeting_handle(tool: str, *, tail: str) -> str:
    return (
        f"{tool} takes the `meeting_uri` handle from teams_list_chats or teams_create_meeting, "
        + "and this value is not one. A meeting handle has exactly one shape:\n"
        + "  teams:///meetings/{join_web_url}\n"
        + "with the join URL percent-encoded. Copy the `meeting_uri` of a tool result word for "
        + f"word. {tail}"
    )


def not_the_organizer(verb: str, *, tail: str) -> str:
    return (
        "Microsoft 365 does not name the signed-in user as the organizer of this meeting. This "
        + f"tool {verb} only a meeting that the signed-in user organizes. {tail}"
    )


async def newest_of[T: MeetingArtifact](
    first_page: GraphCollection[T],
    client: GraphServiceClient,
    *,
    limit: int,
) -> CollectedItems[T]:
    """The newest `limit` artifacts of the meeting, newest first.

    Graph has no `$orderby` here, so the whole collection is read and sorted before the cut;
    cutting first gives a wrong answer that nobody can detect. `capped` means the scan hit
    `MAX_ARTIFACT_SCAN`, where the promise narrows to "newest of the ones read".
    """
    collected = await collect_pages(
        first_page,
        client,
        limit=MAX_ARTIFACT_SCAN,
        max_scanned=MAX_ARTIFACT_SCAN,
    )
    newest = sorted(_told_apart(collected.items), key=_began_at, reverse=True)
    return CollectedItems(items=newest[:limit], capped=collected.capped)


def _told_apart[T: MeetingArtifact](artifacts: list[T]) -> list[T]:
    """One entry per artifact id, in the order Graph first sent it.

    Half of Microsoft's own workaround for the paging reset these collections do
    (https://learn.microsoft.com/en-us/graph/known-issues, Teamwork and communications); the other
    half is following `@odata.nextLink` through empty pages, in `graph_client/pagination.py`. It
    must run before the sort, or a repeat takes one of the `limit` places a distinct artifact was
    owed. An artifact Graph sent with no id is kept: a possible repeat beats a certain loss.
    """
    seen: set[str] = set()
    kept: list[T] = []
    for artifact in artifacts:
        identifier = artifact.id
        if identifier is not None:
            if identifier in seen:
                continue
            seen.add(identifier)
        kept.append(artifact)
    return kept


def _instant(tool: str, argument: str, value: str, *, tail: str) -> datetime | str:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return (
            f"{tool} received {value!r} in `{argument}`. This value is not an ISO-8601 date and "
            + "time. Write the date, the time, and an offset, for example "
            + "`2026-03-02T14:00:00+01:00`. Calculate the date and the time from what the user "
            + f"said. If the day or the hour is ambiguous, ask the user. {tail}"
        )
    if moment.utcoffset() is None:
        return (
            f"{tool} received {value!r} in `{argument}`. This time has no offset, so it does not "
            + "name one instant. Add the offset of the zone of the user, for example "
            + "`2026-03-02T14:00:00+01:00`, or add `Z` for UTC. If the zone is not clear, ask the "
            + f"user. {tail}"
        )
    return moment


def _settled_by(moment: datetime | None, now: datetime) -> bool:
    return moment is not None and as_utc(moment) + ARTIFACT_DELAY_ALLOWANCE < now


def _began_at(artifact: MeetingArtifact) -> datetime:
    began = artifact.created_date_time
    return as_utc(began) if began is not None else datetime.min.replace(tzinfo=UTC)
