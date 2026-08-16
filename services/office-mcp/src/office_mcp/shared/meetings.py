"""How a meeting is reached, which occurrence was asked about, and what "newest" is worth.

Three facts about the *meeting*, not transcripts. They are meeting promises no second tool should
make for itself — a caller cannot see two tools disagreeing about "the latest occurrence", only one
being wrong. `callTranscript` and `callRecording` collections share one `onlineMeeting`, reach it
the same way, and answer empty ambiguously.

`read_transcript` takes one name from here: the permission a transcript resource costs. It does not
resolve (the handle carries the resolved id) or order (the lister called). That is the working
split: the reader cannot repeat the resolve, and the permission it declares is the resource cost,
not the request cost. Had that name lived in a tool file it would be spelled twice (rule 4 forbids
tool files sharing a constant).

## How a meeting is addressed, and the one place the chain can break

Graph documents exactly three delegated ways to reach an `onlineMeeting`
(https://learn.microsoft.com/en-us/graph/api/onlinemeeting-get): by its own `id`, by `joinWebUrl`,
or by `joinMeetingIdSettings/joinMeetingId`. Only the join URL path works from Teams' conversation
side. Only place delegated callers get one: `chat.onlineMeetingInfo.joinWebUrl` in default
`GET /me/chats`. That collection supports `$expand`, `$top`, `$filter`, and `$orderby` only. It has
no `$select`, so the field could not be requested even if it were absent. Chat id is not a route;
neither is chat `webUrl`.

Verified: meeting chats are enumerable with `topic` and recency. Graph documents `joinWebUrl` as
empty when the chat is not a meeting's chat at all. **Not verified**: `joinWebUrl` is populated
when the chat is a meeting's chat, especially for non-organisers. Null join URL is first-class
outcome, not impossible.
No fallback or second route documented. `onlineMeeting.chatInfo.threadId` is filterable in code but
not in Graph docs, so we skip that invented path.

Two limits belong to caller: resolve is documented for attendees; transcript list is not (may refuse
non-organisers). Every artifact API works only if meeting has not expired, depending on tenant
policy roughly 60 days after a one-off
(https://learn.microsoft.com/en-us/microsoftteams/limits-specifications-teams#meeting-expiration).

## The `$filter` on the join URL, and the bug class around it

Graph: "joinWebUrl must be URL encoded". A `%3a` in the stored URL arrives as `%253a` (% is
escaped). `services/teams-mcp` has this defect today, in
`src/transcript/tools/ingest-meeting.tool.ts`. It doubles the quote. Then it hands the raw URL to a
JavaScript SDK that does not encode query parameters. A join URL with `&` or `#` then parses as a
truncated filter. Graph answers `200 OK` with an empty `value`, indistinguishable from "no such
meeting" (silent failure).

Two transforms, only the first ours:
1. OData literal escape: double single quotes inside string literals. Required for correctness and
to stop a crafted URL closing the literal and injecting predicates.
2. Percent-encoding: Python SDK does it correctly, so we do not repeat it. Query parameters use
form-style expansion, escaping everything outside unreserved set. Double-encoding produces `%2525…`
and again an empty value. Tests pin bytes on the wire because this is the failure that looks like
success.

`200 OK` with `value: []` is Graph's documented "no match" for this filter (never 404s). Reported as
its own outcome, not an error.

## The occurrence window, and the shapes a model actually sends

`started_after`/`started_before` exist because recurring series are one meeting to Graph, so
occurrences share one collection distinguished only by artifact start time. Models write in any
shape: `2026-08-11T09:00:00+02:00`, `2026-08-11T09:00:00`, or `2026-08-11`. All three accepted,
resolved against UTC in `OccurrenceWindow` and nowhere else: Graph timestamps artifacts in UTC, so
UTC is the assumption needing no second info. Resolving once at the edge stops downstream comparing
naive with aware datetime (TypeError to caller). Bare date is whole UTC day, not first instant:
same date in both bounds brackets one occurrence; midnight-to-midnight would be empty. The
assumption is stated in each tool's parameter descriptions: `09:00` is different in Zurich; a
window quietly built in wrong zone is worse than one refused.

## Newest first, exactly as far as it is true

"The latest transcript" is why a lister exists. Order must be a property of what was read, not the
page Graph happened to return. Graph documents `$select`, `$filter`, `$top` on transcripts but no
`$orderby`. A walk stopped at limit before sorting returns arbitrary limit artifacts sorted among
themselves, wrong answer with right shape. That is why `newest_in_window` is a named function not
four lines in a tool: the mistake is invisible, so the place it is not made must be one place.

Promise bounded by `MAX_ARTIFACT_SCAN`; sentences worded to that, not "newest of this meeting". Up
to that many artifacts read in whatever order Graph chose. Meetings under the cap: these are the
whole collection, first entry is latest. Series recorded daily for most of a year exceed the cap;
first entry is newest of the read ones; newer ones sit unread. Raising the cap moves the boundary,
not removes it: without `$orderby`, only reading the whole collection makes "newest" exact. Graph
publishes no ceiling on collection size.

## Whether an empty answer means "wait" or "there is none"

`settled` is that inference; deliberately not the verdict. Verdict is different per artifact; tool
owns vocabulary. The *inference* must not exist twice. Reading off meeting instead of window was
wrong answer no caller could detect: series with future `endDateTime` made every empty window
"still processing", including one bracketing an ended occurrence never transcribed — instruction
to poll forever.
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

from office_mcp.graph_client import CollectedItems, GraphCollection, collect_pages
from office_mcp.shared.handles import MeetingHandle

# Resolving join URL to meeting: OnlineMeetings.Read, least privilege for filter, no admin consent.
# Lives with resolve, not tool file, because resolve_meeting pays it regardless of artifact type.
MEETING_PERMISSION = "OnlineMeetings.Read"

# Reading a transcript resource: admin-consented, independent from resolve. Spelled here because
# it is resource cost, not request cost, and two tools read it. Rule 4 forbids tool files sharing
# constants. Tool's GRAPH_PERMISSIONS tuple names its request permissions; gets name from here.
# Typo in one is Entra scope rejection, sign-in fails for everybody.
TRANSCRIPT_PERMISSION = "OnlineMeetingTranscript.Read.All"

# Artifacts one listing may scan. This is "newest first" cost: no orderby, only looking at the
# collection reveals newest. Bound on artifacts not requests (what collect_pages can bound). Graph
# chooses page size. 200 is 4x largest limit offered; meets/series recorded daily for most of a
# year hit the cap. Exceeding it: scan incomplete, no guess, "newest" of the read ones.
MAX_ARTIFACT_SCAN = 200

# How long after window closes or meeting ends does missing artifact stay "not ready" not "never
# made". Microsoft publishes no SLA or "processing" status. Generous: wait once when nothing
# arrives (one call cost) beats saying "no transcript" when it arrives in ten minutes
# (undetectable wrong).
ARTIFACT_DELAY_ALLOWANCE = timedelta(hours=4)

type _MeetingsQuery = OnlineMeetingsRequestBuilder.OnlineMeetingsRequestBuilderGetQueryParameters


class MeetingArtifact(Protocol):
    """The one property a window needs: when artifact began.

    Structural not nominal: callTranscript and callRecording are unrelated generated classes both
    carrying createdDateTime.
    """

    @property
    def created_date_time(self) -> datetime | None: ...


@dataclass(frozen=True, slots=True)
class OccurrenceWindow:
    """Which occurrence was asked about, as two timezone-aware instants.

    Type not two args because window decides what is kept and whether empty means "wait" or "never
    made". Use `of` constructor.
    """

    started_after: datetime | None
    started_before: datetime | None

    @classmethod
    def of(
        cls, started_after: date | datetime | None, started_before: date | datetime | None
    ) -> Self:
        """Window from bounds, resolving naive datetimes against UTC. Bare date is whole UTC day."""
        return cls(_first_instant(started_after), _last_instant(started_before))

    def holds(self, artifact: MeetingArtifact) -> bool:
        """Whether artifact began inside window.

        Missing createdDateTime kept when no window asked for, dropped when one was.
        """
        if self.started_after is None and self.started_before is None:
            return True
        began = artifact.created_date_time
        if began is None:
            return False
        # Aware even though Graph's own timestamps carry `Z`: this comparison is the one that used
        # to raise, and it must not depend on a payload's punctuation to stay safe.
        began = as_utc(began)
        if self.started_after is not None and began < self.started_after:
            return False
        return not (self.started_before is not None and began > self.started_before)

    def settled(self, meeting: OnlineMeeting) -> bool:
        """Whether empty answer means "there is none" not "not yet".

        Two independent pieces of evidence either settles it: window's end far past (anything
        falling in would land) or meeting's end far past. Answers caller who asked no window.
        Absent evidence never settles (that is cheaper wrong answer).

        Trap: a series with future `endDateTime` makes any empty window "still processing"
        including one bracketing an ended occurrence never transcribed — check window settlement
        separately.
        """
        now = datetime.now(UTC)
        return _settled_by(self.started_before, now) or _settled_by(meeting.end_date_time, now)


def as_utc(moment: datetime) -> datetime:
    """Moment as aware datetime, reading naive as UTC.

    UTC assumption belongs to window; resolving here prevents downstream naive-aware comparison
    TypeError.
    """
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


async def resolve_meeting(
    client: GraphServiceClient, handle: MeetingHandle
) -> OnlineMeeting | None:
    """Meeting whose joinWebUrl is handle's, or None if Graph matched none.

    One request. Filter must exist exactly once. 200 OK with empty value is "no match", not 404.
    """
    escaped = handle.join_web_url.replace("'", "''")
    configuration = RequestConfiguration[_MeetingsQuery](
        query_parameters=OnlineMeetingsRequestBuilder.OnlineMeetingsRequestBuilderGetQueryParameters(
            filter=f"JoinWebUrl eq '{escaped}'"
        )
    )
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
    """Limit newest artifacts of meeting in window, newest first.

    Read everything window holds, sort, cut to limit — Graph has no orderby. Stop-at-limit-before-
    sort is undetectable wrong answer. `capped` means only that the scan hit `MAX_ARTIFACT_SCAN`.
    It does not mean the window held more than `limit` artifacts. Read the returned count for that.

    Where promise stops being "newest of this meeting" and starts being "newest of read ones". With
    no orderby, only reading everything makes newest exact. Cap prevents unbounded walk on
    unceilinged collection.
    """
    collected = await collect_pages(
        first_page,
        client,
        limit=MAX_ARTIFACT_SCAN,
        matches=window.holds,
        max_scanned=MAX_ARTIFACT_SCAN,
    )
    newest = sorted(collected.items, key=_began_at, reverse=True)
    return CollectedItems(items=newest[:limit], capped=collected.capped)


def _first_instant(bound: date | datetime | None) -> datetime | None:
    """Earliest instant bound includes, or None."""
    if bound is None:
        return None
    if isinstance(bound, datetime):
        return as_utc(bound)
    return datetime.combine(bound, time.min, tzinfo=UTC)


def _last_instant(bound: date | datetime | None) -> datetime | None:
    """Latest instant bound includes, or None."""
    if bound is None:
        return None
    if isinstance(bound, datetime):
        return as_utc(bound)
    return datetime.combine(bound, time.max, tzinfo=UTC)


def _settled_by(moment: datetime | None, now: datetime) -> bool:
    """Whether moment is far past enough that artifact would have arrived."""
    return moment is not None and as_utc(moment) + ARTIFACT_DELAY_ALLOWANCE < now


def _began_at(artifact: MeetingArtifact) -> datetime:
    """Sort key: when artifact began, or epoch if Graph didn't say.

    Aware (prevents sort TypeError).
    """
    began = artifact.created_date_time
    return as_utc(began) if began is not None else datetime.min.replace(tzinfo=UTC)
