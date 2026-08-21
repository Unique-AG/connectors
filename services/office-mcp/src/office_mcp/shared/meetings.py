"""How a meeting is reached, which occurrence was asked about, and what "newest" is worth.

Graph documents exactly three delegated ways to reach an `onlineMeeting`
(https://learn.microsoft.com/en-us/graph/api/onlinemeeting-get): by its own `id`, by `joinWebUrl`,
or by `joinMeetingIdSettings/joinMeetingId`. Only the join URL works from Teams' conversation side,
and the only place a delegated caller gets one is `chat.onlineMeetingInfo.joinWebUrl` in the default
`GET /me/chats`, which has no `$select`. Whether that field is populated for a non-organiser is
**not verified**, so a null join URL is a first-class outcome. Every artifact API works only while
the meeting has not expired, roughly 60 days after a one-off
(https://learn.microsoft.com/en-us/microsoftteams/limits-specifications-teams#meeting-expiration).

Trap: Graph says "joinWebUrl must be URL encoded", and encoding it here is how that goes wrong.
Encode it twice and a `%3a` in the stored URL arrives as `%253a`. The Python SDK expands query
parameters form-style, escaping everything outside the unreserved set, so percent-encoding here as
well produces `%2525…`; Graph then answers `200 OK` with an empty `value`, its documented "no match"
and indistinguishable from "no such meeting", so the failure is silent. `services/teams-mcp` has a
defect of this class today in `src/transcript/tools/ingest-meeting.tool.ts`. The one transform that
is ours is the OData literal escape, doubling single quotes inside a string literal: required for
correctness, and it stops a crafted URL closing the literal and injecting predicates. The tests pin
the bytes on the wire, because this is the failure that looks like success.

A bare date bound is the whole UTC day rather than its first instant, so the same date in both
bounds brackets one occurrence where midnight to midnight would be empty.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol, Self

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.online_meeting import OnlineMeeting
from msgraph.generated.users.item.online_meetings.online_meetings_request_builder import (
    OnlineMeetingsRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import CollectedItems, GraphCollection, collect_pages, graph_step
from office_mcp.shared.handles import MeetingHandle

# Least privilege for the resolve filter, and it needs no admin consent.
MEETING_PERMISSION = "OnlineMeetings.Read"

# Both meeting tools pay the resolve request, and a step named by each of them would be one request
# under two names. `newest_in_window` declares none: it walks a collection the *tool* named.
STEP_RESOLVE_MEETING = "resolve_meeting"

# Reading a transcript or a recording resource: admin-consented, and a resource cost rather than a
# request cost. Two tools read `TRANSCRIPT_PERMISSION`, and a second spelling of either name is a
# scope Entra rejects, which fails sign-in for everybody.
TRANSCRIPT_PERMISSION = "OnlineMeetingTranscript.Read.All"
RECORDING_PERMISSION = "OnlineMeetingRecording.Read.All"

# How many artifacts one listing may scan. A bound on artifacts rather than on requests, because
# that is what `collect_pages` can bound and Graph chooses the page size. 200 is four times the
# largest limit offered.
MAX_ARTIFACT_SCAN = 200

# How long after the window closes, or the meeting ends, a missing artifact still counts as "not
# ready" rather than "never made". Microsoft publishes no SLA and no "processing" status. Generous
# on purpose: saying "no transcript" ten minutes before it arrives is wrong in a way nobody detects.
ARTIFACT_DELAY_ALLOWANCE = timedelta(hours=4)

type _MeetingsQuery = OnlineMeetingsRequestBuilder.OnlineMeetingsRequestBuilderGetQueryParameters


class MeetingArtifact(Protocol):
    """When an artifact began and which artifact it is. Structural rather than nominal, because
    `callTranscript` and `callRecording` are unrelated generated classes."""

    @property
    def id(self) -> str | None: ...

    @property
    def created_date_time(self) -> datetime | None: ...


@dataclass(frozen=True, slots=True)
class OccurrenceWindow:
    """Which occurrence was asked about, as two timezone-aware instants. Build it with `of`."""

    started_after: datetime | None
    started_before: datetime | None

    @classmethod
    def of(
        cls, started_after: date | datetime | None, started_before: date | datetime | None
    ) -> Self:
        """Window from these bounds. A naive datetime is UTC. A bare date is a whole UTC day."""
        return cls(_first_instant(started_after), _last_instant(started_before))

    def holds(self, artifact: MeetingArtifact) -> bool:
        """Whether the artifact began inside the window. A missing `createdDateTime` is kept when no
        window was asked for, dropped when one was."""
        if self.started_after is None and self.started_before is None:
            return True
        began = artifact.created_date_time
        if began is None:
            return False
        # Aware even though Graph's own timestamps carry `Z`: this is the comparison that used to
        # raise, and it must not depend on a payload's punctuation.
        began = as_utc(began)
        if self.started_after is not None and began < self.started_after:
            return False
        return not (self.started_before is not None and began > self.started_before)

    def settled(self, meeting: OnlineMeeting) -> bool:
        """Whether an empty answer means "there is none" rather than "not yet".

        Trap: a series with a future `endDateTime` makes any empty window "still processing",
        including one bracketing an ended occurrence that was never transcribed, so the window is
        checked for settlement separately.
        """
        now = datetime.now(UTC)
        return _settled_by(self.started_before, now) or _settled_by(meeting.end_date_time, now)


def as_utc(moment: datetime) -> datetime:
    """The moment as an aware datetime, reading a naive one as UTC, so nothing downstream compares a
    naive datetime with an aware one and raises `TypeError`."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


async def resolve_meeting(
    client: GraphServiceClient, handle: MeetingHandle
) -> OnlineMeeting | None:
    """The meeting whose `joinWebUrl` is the handle's, or None if Graph matched none. `200 OK` with
    an empty value is "no match", not a 404."""
    escaped = handle.join_web_url.replace("'", "''")
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


async def newest_in_window[T: MeetingArtifact](
    first_page: GraphCollection[T],
    client: GraphServiceClient,
    *,
    window: OccurrenceWindow,
    limit: int,
) -> CollectedItems[T]:
    """The newest `limit` artifacts of the meeting inside `window`, newest first.

    Everything the window holds is read, then sorted, then cut to `limit`: Graph has no `$orderby`,
    and stopping at `limit` before the sort is a wrong answer nobody can detect. `capped` means the
    scan hit `MAX_ARTIFACT_SCAN`, where the promise stops being "newest of this meeting" and starts
    being "newest of the ones read". It does not mean the window held more than `limit`.
    """
    collected = await collect_pages(
        first_page,
        client,
        limit=MAX_ARTIFACT_SCAN,
        matches=window.holds,
        max_scanned=MAX_ARTIFACT_SCAN,
    )
    newest = sorted(_told_apart(collected.items), key=_began_at, reverse=True)
    return CollectedItems(items=newest[:limit], capped=collected.capped)


def _told_apart[T: MeetingArtifact](artifacts: list[T]) -> list[T]:
    """One entry per artifact id, in the order Graph first sent it.

    The other half of Microsoft's own workaround for the paging reset these two collections are
    documented to do (https://learn.microsoft.com/en-us/graph/known-issues, Teamwork and
    communications): keep following `@odata.nextLink` through empty pages, which
    `graph_client/pagination.py` does, and de-duplicate by id, which this does.

    Before the sort, not after the cut: a repeat surviving into the sort takes one of the `limit`
    places a distinct artifact was owed. An artifact Graph sent with no id is kept, because a
    possible repeat beats a certain loss.
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


def _first_instant(bound: date | datetime | None) -> datetime | None:
    if bound is None:
        return None
    if isinstance(bound, datetime):
        return as_utc(bound)
    return datetime.combine(bound, time.min, tzinfo=UTC)


def _last_instant(bound: date | datetime | None) -> datetime | None:
    if bound is None:
        return None
    if isinstance(bound, datetime):
        return as_utc(bound)
    return datetime.combine(bound, time.max, tzinfo=UTC)


def _settled_by(moment: datetime | None, now: datetime) -> bool:
    """Whether the moment is far enough past that an artifact would have arrived."""
    return moment is not None and as_utc(moment) + ARTIFACT_DELAY_ALLOWANCE < now


def _began_at(artifact: MeetingArtifact) -> datetime:
    """Sort key: when the artifact began, or the epoch if Graph did not say."""
    began = artifact.created_date_time
    return as_utc(began) if began is not None else datetime.min.replace(tzinfo=UTC)
