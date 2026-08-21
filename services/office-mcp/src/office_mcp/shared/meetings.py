"""How a meeting is reached, which occurrence was asked about, and what "newest" is worth.

Three facts about the *meeting*, not about transcripts. They are meeting promises no second tool
should make for itself: a caller cannot see two tools disagreeing about "the latest occurrence",
only one of them being wrong. The `callTranscript` and `callRecording` collections share one
`onlineMeeting`, reach it the same way, and answer empty ambiguously.

## How a meeting is addressed, and the one place the chain can break

Graph documents exactly three delegated ways to reach an `onlineMeeting`
(https://learn.microsoft.com/en-us/graph/api/onlinemeeting-get): by its own `id`, by `joinWebUrl`,
or by `joinMeetingIdSettings/joinMeetingId`. Only the join URL works from Teams' conversation side,
and the only place a delegated caller gets one is `chat.onlineMeetingInfo.joinWebUrl` in the default
`GET /me/chats`. That collection supports `$expand`, `$top`, `$filter` and `$orderby` only. It has
no `$select`, so the field could not be requested even if it were absent. Neither the chat id nor
the chat `webUrl` is a route.

Verified: meeting chats are enumerable with `topic` and recency, and Graph documents `joinWebUrl` as
empty when the chat is not a meeting's chat at all. **Not verified**: that `joinWebUrl` is populated
when the chat is a meeting's chat, especially for non-organisers. A null join URL is a first-class
outcome rather than an impossible one. Graph documents no fallback and no second route, and
`onlineMeeting.chatInfo.threadId` is filterable in code but not in Graph's docs, so that invented
path is not taken.

Two limits belong to the caller. The resolve is documented for attendees and the transcript list is
not, so the list may refuse a non-organiser. Every artifact API works only while the meeting has not
expired. Tenant policy puts expiry at roughly 60 days after a one-off
(https://learn.microsoft.com/en-us/microsoftteams/limits-specifications-teams#meeting-expiration).

## The `$filter` on the join URL, and the bug class around it

Graph: "joinWebUrl must be URL encoded". Encode it twice and a `%3a` in the stored URL arrives as
`%253a`, because the `%` is itself escaped. `services/teams-mcp` has that defect today, in
`src/transcript/tools/ingest-meeting.tool.ts`: it doubles the quoting, then hands the raw URL to a
JavaScript SDK that does not encode query parameters, so a join URL carrying `&` or `#` parses as a
truncated filter. Graph answers `200 OK` with an empty `value`, indistinguishable from "no such
meeting", so the failure is silent.

Two transforms, and only the first is ours. The OData literal escape doubles single quotes inside a
string literal. It is required for correctness, and it stops a crafted URL closing the literal and
injecting predicates. Percent-encoding is the Python SDK's: it expands query parameters form-style,
escaping everything outside the unreserved set, so encoding here as well produces `%2525…` and again
an empty value. The tests pin the bytes on the wire, because this is the failure that looks like
success.

`200 OK` with `value: []` is Graph's documented "no match" for this filter. Graph never 404s here,
and the empty value is reported as its own outcome rather than as an error.

## The occurrence window, and the shapes a model actually sends

`started_after` and `started_before` exist because a recurring series is one meeting to Graph, so
its occurrences share one collection and are told apart only by artifact start time. Models write
any of `2026-08-11T09:00:00+02:00`, `2026-08-11T09:00:00`, or `2026-08-11`, and all three are
resolved against UTC in `OccurrenceWindow` and nowhere else: Graph timestamps artifacts in UTC, so
UTC is the assumption that needs no second piece of information, and resolving once at the edge
stops anything downstream comparing a naive datetime with an aware one, a comparison that raises
`TypeError` at the caller. A bare date is the whole UTC day rather than its first instant, so the
same date in both bounds brackets one occurrence where midnight to midnight would be empty. Each
tool's parameter descriptions state the assumption: `09:00` is a different instant in Zurich, and a
window quietly built in the wrong zone is worse than one refused.

## Newest first, exactly as far as it is true

"The latest transcript" is why a lister exists, so the order has to be a property of what was read
rather than of the page Graph happened to return. Graph documents `$select`, `$filter` and `$top` on
transcripts but no `$orderby`, and a walk stopped at `limit` before sorting returns an arbitrary
`limit` artifacts sorted among themselves: the wrong answer in the right shape. That is why
`newest_in_window` is a named function rather than four lines in a tool: the mistake is invisible,
so the place it is not made has to be one place.

`MAX_ARTIFACT_SCAN` bounds the promise, and the sentences are worded to that rather than to "newest
of this meeting". Up to that many artifacts are read, in whatever order Graph chose. For a meeting
under the cap those are the whole collection and the first entry is the latest. A series recorded
daily for most of a year exceeds the cap, so the first entry is the newest of the ones read and
newer ones sit unread. Raising the cap moves that boundary rather than removing it, and Graph
publishes no ceiling on collection size.

## Whether an empty answer means "wait" or "there is none"

`settled` is that inference, and deliberately not the verdict: the verdict differs per artifact and
each tool owns its own vocabulary. The inference must not exist twice, because reading it off the
meeting instead of the window was a wrong answer no caller could detect, and the instruction it gave
a caller was to poll forever.
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

# Resolving a join URL to a meeting: `OnlineMeetings.Read` is least privilege for the filter and
# needs no admin consent. It lives with the resolve rather than in a tool file, because
# `resolve_meeting` pays it whatever artifact the tool went on to ask for.
MEETING_PERMISSION = "OnlineMeetings.Read"

# What the resolve request is counted as, declared here for the same reason the permission above is:
# both meeting tools pay it, and a step named by each of them would be one request under two names.
# `newest_in_window` deliberately declares none. It walks a collection the *tool* named, so one
# listing is counted under that tool's own step rather than split in two.
STEP_RESOLVE_MEETING = "resolve_meeting"

# Reading a transcript or a recording resource: admin-consented, independent of the resolve, and a
# resource cost rather than a request cost. Each tool's `GRAPH_PERMISSIONS` names its request
# permissions by taking the name from here. A typo in a second spelling is a scope Entra rejects,
# and sign-in then fails for everybody. `TRANSCRIPT_PERMISSION` is the one two tools read,
# `list_meeting_transcripts` and `read_transcript`, and rule 4 forbids tool files sharing a
# constant. `RECORDING_PERMISSION` has one reader, `list_meeting_recordings`, and is spelled beside
# `TRANSCRIPT_PERMISSION` because it is the same kind of cost. `read_transcript` takes
# `TRANSCRIPT_PERMISSION` and nothing else from this module: its handle carries the resolved id, so
# it does not resolve, and `list_meeting_transcripts` already ordered, so it does not order.
TRANSCRIPT_PERMISSION = "OnlineMeetingTranscript.Read.All"
RECORDING_PERMISSION = "OnlineMeetingRecording.Read.All"

# How many artifacts one listing may scan, and what "newest first" costs. A bound on artifacts
# rather than on requests, because that is what `collect_pages` can bound and Graph chooses the page
# size. 200 is four times the largest limit offered.
MAX_ARTIFACT_SCAN = 200

# How long after the window closes, or the meeting ends, a missing artifact still counts as "not
# ready" rather than "never made". Microsoft publishes no SLA and no "processing" status. Generous
# on purpose: waiting once when nothing has arrived costs one call, and saying "no transcript" ten
# minutes before it arrives is wrong in a way nobody detects.
ARTIFACT_DELAY_ALLOWANCE = timedelta(hours=4)

type _MeetingsQuery = OnlineMeetingsRequestBuilder.OnlineMeetingsRequestBuilderGetQueryParameters


class MeetingArtifact(Protocol):
    """The two properties this module needs: when an artifact began, and which artifact it is.

    Structural rather than nominal, because `callTranscript` and `callRecording` are unrelated
    generated classes. Both carry `createdDateTime`, and both are entities, so both carry an id.
    """

    @property
    def id(self) -> str | None: ...

    @property
    def created_date_time(self) -> datetime | None: ...


@dataclass(frozen=True, slots=True)
class OccurrenceWindow:
    """Which occurrence was asked about, as two timezone-aware instants.

    A type rather than two arguments, because the window decides what is kept and whether an empty
    answer means "wait" or "never made". Build it with `of`.
    """

    started_after: datetime | None
    started_before: datetime | None

    @classmethod
    def of(
        cls, started_after: date | datetime | None, started_before: date | datetime | None
    ) -> Self:
        """Window from these bounds. A naive datetime is UTC. A bare date is a whole UTC day."""
        return cls(_first_instant(started_after), _last_instant(started_before))

    def holds(self, artifact: MeetingArtifact) -> bool:
        """Whether the artifact began inside the window.

        A missing `createdDateTime` is kept when no window was asked for, dropped when one was.
        """
        if self.started_after is None and self.started_before is None:
            return True
        began = artifact.created_date_time
        if began is None:
            return False
        # Aware even though Graph's own timestamps carry `Z`: this is the comparison that used to
        # raise, and it must not depend on a payload's punctuation to stay safe.
        began = as_utc(began)
        if self.started_after is not None and began < self.started_after:
            return False
        return not (self.started_before is not None and began > self.started_before)

    def settled(self, meeting: OnlineMeeting) -> bool:
        """Whether an empty answer means "there is none" rather than "not yet".

        Either piece of evidence settles it: the window's end is far enough past that anything
        falling inside it would have landed, or the meeting's end is far enough past. The second
        answers a caller who asked for no window. Absent evidence never settles it, because an
        unsettled answer is the cheaper wrong one.

        Trap: a series with a future `endDateTime` makes any empty window "still processing",
        including one bracketing an ended occurrence that was never transcribed, so the window is
        checked for settlement separately.
        """
        now = datetime.now(UTC)
        return _settled_by(self.started_before, now) or _settled_by(meeting.end_date_time, now)


def as_utc(moment: datetime) -> datetime:
    """The moment as an aware datetime, reading a naive one as UTC.

    The UTC assumption belongs to the window. Resolving here stops anything downstream comparing a
    naive datetime with an aware one, a comparison that raises `TypeError`.
    """
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


async def resolve_meeting(
    client: GraphServiceClient, handle: MeetingHandle
) -> OnlineMeeting | None:
    """The meeting whose `joinWebUrl` is the handle's, or None if Graph matched none.

    One request. The filter must exist exactly once. `200 OK` with an empty value is "no match",
    not a 404.
    """
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

    Everything the window holds is read, then sorted, then cut to `limit`. Graph has no `$orderby`,
    and stopping at `limit` before the sort is a wrong answer nobody can detect. `capped` means only
    that the scan hit `MAX_ARTIFACT_SCAN`, which is where the promise stops being "newest of this
    meeting" and starts being "newest of the ones read". It does not mean the window held more than
    `limit` artifacts. Read the returned count for that.
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
    communications): "Continue following `@odata.nextLink` even when the collection is empty.
    De-duplicate subsequent items by tracking the **id** property of each recording or transcript."
    `graph_client/pagination.py` does the following. This function does the de-duplicating.

    Here rather than in `collect_pages`, because it is a property of these two Graph collections
    rather than of paging, and that is also the scope Microsoft gives it. A general walk has no
    business assuming its items have an id, or that two with the same one are the same thing.

    Before the sort, not after the cut: a repeat that survived into the sort would take one of the
    `limit` places a distinct artifact was owed, so a caller asking for the newest three could be
    handed the same recording twice and never learn there was a third.

    An artifact Graph sent with no id at all is kept. It cannot be told apart from anything, so the
    choice is between a possible repeat and a certain loss, and a lost recording is worse.
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
    """The earliest instant the bound includes, or None."""
    if bound is None:
        return None
    if isinstance(bound, datetime):
        return as_utc(bound)
    return datetime.combine(bound, time.min, tzinfo=UTC)


def _last_instant(bound: date | datetime | None) -> datetime | None:
    """The latest instant the bound includes, or None."""
    if bound is None:
        return None
    if isinstance(bound, datetime):
        return as_utc(bound)
    return datetime.combine(bound, time.max, tzinfo=UTC)


def _settled_by(moment: datetime | None, now: datetime) -> bool:
    """Whether the moment is far enough past that an artifact would have arrived."""
    return moment is not None and as_utc(moment) + ARTIFACT_DELAY_ALLOWANCE < now


def _began_at(artifact: MeetingArtifact) -> datetime:
    """Sort key: when the artifact began, or the epoch if Graph did not say.

    Aware, so the sort cannot raise `TypeError`.
    """
    began = artifact.created_date_time
    return as_utc(began) if began is not None else datetime.min.replace(tzinfo=UTC)
