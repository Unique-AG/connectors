"""How a meeting is reached, which occurrence was asked about, and what "newest" is worth.

None of those three is a fact about transcripts. They are facts about the *meeting*, and about the
artifacts Graph hangs off one: a `callTranscript` collection and a `callRecording` collection on the
same `onlineMeeting`, reached through the same resolve, ordered the same way (which is to say not at
all), and answered empty in the same ambiguous way. Everything in this module is therefore a promise
a second tool over the same meeting would otherwise make for itself, and the cost of that is the
test for belonging here: a caller cannot see two tools disagreeing about "the latest occurrence", it
can only see one of them being wrong.

That is also why this is here while one tool calls it. The alternative is not "keep it in the tool
file and move it when a second caller arrives" — it is a later diff that moves a promise, reviewed
as a refactor rather than as a decision, with the window spending that whole time as one tool's
private helper. A private helper is exactly what the second caller copies.

## How a meeting is addressed, and the one place the chain can break

Graph documents exactly three delegated ways to reach an `onlineMeeting`
(https://learn.microsoft.com/en-us/graph/api/onlinemeeting-get): by its own `id`, by `joinWebUrl`,
or by `joinMeetingIdSettings/joinMeetingId`. A chat id is not one of them, and neither is a chat's
`webUrl`. So the only route from Teams' conversation side to the meeting side is the join URL, and
the only place a delegated caller is given one is `chat.onlineMeetingInfo.joinWebUrl` — a property
of the `chat` resource, present in the default projection of `GET /me/chats` (that collection
supports `$expand`, `$top`, `$filter` and `$orderby` and nothing else, so it could not be asked for
explicitly even if it were absent), and documented as "empty" when the chat is not a meeting's.

**What is verified and what is not.** Meeting chats being enumerable with a descriptive `topic` and
a recency timestamp is confirmed against a live tenant. That `onlineMeetingInfo.joinWebUrl` is
*populated* — in general, and specifically for a meeting the signed-in user did not organise — is
**not**: the property is documented on the resource and modelled by the SDK, and no doc says it is
organiser-only, but no live call has been made that asked for it. So a null join URL is a first-
class outcome rather than an impossible one: `list_chats` reports no `meeting_uri` for that chat,
and there is no fallback, because there is no documented second route. `onlineMeeting` does carry a
`chatInfo.threadId`, and a `$filter` on it would be exactly the invented path this module refuses
to ship: Graph documents neither that property as filterable nor any lookup by it.

Two further limits belong to the caller rather than to the code. The resolve step is documented for
attendees — "These request URLs accept both the organizer's and the invited attendee's user token
(delegated permission)" — but the transcript *list* is not: its reference page documents
`OnlineMeetingTranscript.Read.All` and says nothing about non-organisers, so a participant may be
refused where the organiser succeeds. And every artifact API "works for a meeting only if the
meeting has not expired", which is roughly 60 days for a one-off
(https://learn.microsoft.com/en-us/microsoftteams/limits-specifications-teams#meeting-expiration).

## The `$filter` on the join URL, and the bug class around it

Graph's note is one line — "**joinWebUrl** must be URL encoded" — and its worked example shows how
far that goes: a `%3a` already inside the stored URL arrives as `%253a`, because the `%` is itself
escaped. `services/teams-mcp` gets this wrong today (`src/transcript/tools/ingest-meeting.tool.ts`
doubles the quote and then hands the raw URL to a JavaScript SDK that concatenates query parameters
without encoding), and the failure is silent: a join URL carrying `&` or `#` — real ones do — makes
Graph parse a truncated filter and answer `200 OK` with an empty `value`, which reads exactly like
"no such meeting".

Here the two transforms are separated, and only the first is ours:

1. **OData literal escape.** A single quote inside an OData string literal is doubled. Required for
   correctness and to stop a crafted URL closing the literal and appending predicates of its own.
2. **Percent-encoding**, which the Python SDK does correctly and which is therefore not repeated:
   `$filter` is a query parameter of a URI template, and form-style expansion escapes everything
   outside the unreserved set — including `%`, `&`, `#`, `?` and `=`. Encoding it a second time
   would produce `%2525…` and, again, an empty `value`. The tests pin the bytes that reach the
   wire, because this is the failure that looks like an answer.

`200 OK` with `value: []` is Graph's documented "no match" for this filter — it never 404s — so it
is reported as its own outcome and not as an error.

## The occurrence window, and the shapes a model actually sends

`started_after`/`started_before` exist for one reason: a recurring series is a single meeting to
Graph, so its occurrences share one artifact collection and the only thing telling them apart is
when the artifact began. That makes the window the thing a model reaches for most, and it arrives
in whatever shape the model wrote — `2026-08-11T09:00:00+02:00`, but just as often
`2026-08-11T09:00:00` or `2026-08-11`, because that is how a date gets written when nobody is
watching. All three are accepted and resolved against UTC, in `OccurrenceWindow` and nowhere else:
Graph timestamps every artifact in UTC, so UTC is the assumption that needs no second piece of
information, and resolving once at the edge is what stops anything downstream comparing a naive
datetime with an aware one — which is a `TypeError` raised at a caller who did nothing wrong, not a
wrong answer it could notice. A bare date is a whole UTC day rather than its first instant, because
writing the same date in both bounds is how one occurrence gets bracketed and midnight-to-midnight
would be an empty window reported as an answer. The assumption is stated in each tool's own
parameter descriptions, where a model reads it: `09:00` is a different instant in Zurich, and a
window quietly built in the wrong zone is worse than one that was refused.

## Newest first, exactly as far as it is true

"The latest transcript of this series" is the question a lister exists for, so the order has to be
a property of what was *read* and not of the page Graph happened to answer with — Graph documents
`$select`, `$filter` and `$top` on these collections and no `$orderby` at all
(https://learn.microsoft.com/en-us/graph/api/onlinemeeting-list-transcripts), and a walk that
stopped at `limit` before sorting would return an arbitrary `limit` artifacts sorted among
themselves and call them the newest. That is a wrong answer with the shape of a right one, which is
the whole reason `newest_in_window` is a named function rather than four lines inside a tool: the
mistake is invisible in the answer, so the place it is not made has to be one place.

What the promise is worth is bounded by `MAX_ARTIFACT_SCAN`, and every sentence a model reads is
worded to that bound rather than to "the newest of this meeting". Up to that many artifacts are
read, in whatever order Graph chose; for a meeting with no more than that they are the whole
collection and the first entry is the latest outright, which covers every meeting but a series
recorded daily for the better part of a year. Past it the first entry is the newest of the
artifacts that were *read*, and a newer one can sit in the part that was not. Raising the cap would
move that boundary rather than remove it: with no `$orderby` to ask the newest for, nothing short of
reading the whole collection makes the word exact, and Graph publishes no ceiling on how large that
collection can be.

## Whether an empty answer means "wait" or "there is none"

`settled` is that inference and it is deliberately not the verdict: the verdict is a different word
per artifact — `not_transcribed` is one of them — and the tool that answers owns its own vocabulary.
What must not exist twice is the *inference*. Reading it off the meeting instead of off the window
was a wrong answer no caller could detect — a recurring series whose `endDateTime` is in the future
made every empty window "still processing", including one bracketing an occurrence that ended weeks
ago and was never transcribed, which is an instruction to poll forever.
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

# Resolving a join URL to a meeting is `OnlineMeetings.Read`, the least privilege Graph documents
# for the filter, and it needs no admin consent. It lives with the resolve rather than in a tool
# file because it is the permission `resolve_meeting` spends, whichever artifact the tool that
# called it went on to ask about — reading either artifact is a further, admin-consented permission
# that the tool declares for itself.
MEETING_PERMISSION = "OnlineMeetings.Read"

# Reading a transcript resource, which is admin-consented and grantable independently of the
# resolve above. Spelled here rather than in the tool file that declares it because it is the
# permission the *resource* costs rather than the permission one tool's request costs: anything
# else reaching a `callTranscript` needs exactly this one, and rule 4 forbids it importing a tool
# file to find out. A tool-side constant is therefore a string spelled twice by construction, and
# two spellings of a permission is not a tidiness problem — the authorize request carries whatever
# they say, and a typo in one of them is a scope Entra rejects and a sign-in that fails for
# everybody (see `shared/seam.py`'s `REQUESTABLE_PERMISSIONS`, which is what holds the spelling to
# Microsoft's).
#
# Declaring is still each tool's own: a tool's `GRAPH_PERMISSIONS` tuple is what its 403 and its
# AADSTS65001 are worded from, so it names the permissions its own request is made under and takes
# the name from here rather than re-typing it.
TRANSCRIPT_PERMISSION = "OnlineMeetingTranscript.Read.All"

# How many of a meeting's artifacts one listing may look at, whichever artifact it is. This is what
# "newest first" costs: Graph documents no `$orderby` on either collection, so the newest can only
# be known by looking at the collection, and a walk that stopped at `limit` would be sorting an
# arbitrary handful of it (see `newest_in_window`). The bound is on artifacts rather than on
# requests because that is what `collect_pages` can bound — Graph chooses the page size here and
# publishes none — so the honest statement of the cost is "at most this many artifacts are looked
# at, in however many pages Graph answers them in".
#
# 200 is four times the largest `limit` a lister offers and far past any real meeting: a meeting
# accumulates one artifact per occurrence, so reaching this takes a series that has run daily for
# the better part of a year *and* been recorded every time. A meeting that does exceed it is not
# answered with a guess — the scan is reported as incomplete, no absence is asserted, and "newest
# first" is stated as what it then is, an order over the artifacts that were read.
#
# Raising it is not the fix for either of those, which is why the number is boring: a bigger cap
# moves the boundary and leaves both statements needing the same qualification, because Graph
# offers no `$orderby` to ask the newest for and no date `$filter` to make the window the server's.
MAX_ARTIFACT_SCAN = 200

# How long after a window closes — or after a meeting ends, where no window was asked for — a
# missing artifact is still called "not ready" rather than "never made". Microsoft publishes no SLA
# and no "processing" status for the availability of a transcript or of a recording, so this is not
# a promise about Graph — it is which of two opposite pieces of advice to give when the evidence is
# the same empty collection. Generous on purpose: telling a caller to wait once when nothing will
# ever arrive costs one call, while telling it a transcript does not exist when it is ten minutes
# away is a wrong answer it cannot detect.
ARTIFACT_DELAY_ALLOWANCE = timedelta(hours=4)

type _MeetingsQuery = OnlineMeetingsRequestBuilder.OnlineMeetingsRequestBuilderGetQueryParameters


class MeetingArtifact(Protocol):
    """The one property a window needs of a meeting artifact: when it began.

    Structural rather than nominal because there are two of these in Graph and they are unrelated
    generated classes: `callTranscript` and `callRecording` both carry `createdDateTime` and nothing
    else below is read. Naming the property rather than one of the classes is what keeps this module
    about a meeting rather than about transcripts — the window scopes an occurrence, and which
    artifact was hung off that occurrence is not its business.
    """

    @property
    def created_date_time(self) -> datetime | None: ...


@dataclass(frozen=True, slots=True)
class OccurrenceWindow:
    """Which occurrence was asked about, as two instants that are always timezone-aware.

    A type rather than two arguments threaded through, because the window decides two things that
    have to agree: which artifacts are kept, and — when none are — whether an empty answer means
    "wait" or "there is none".

    `of` is the only constructor a caller should use: it takes the shapes a model actually sends and
    resolves them, so that no comparison downstream can meet a naive datetime.
    """

    started_after: datetime | None
    started_before: datetime | None

    @classmethod
    def of(
        cls, started_after: date | datetime | None, started_before: date | datetime | None
    ) -> Self:
        """A window from bounds as given, resolving anything that named no timezone against UTC.

        A bare date names a whole UTC day: `started_after` takes its first instant and
        `started_before` its last, so the same date in both is that one day rather than the empty
        span between one midnight and itself.
        """
        return cls(_first_instant(started_after), _last_instant(started_before))

    def holds(self, artifact: MeetingArtifact) -> bool:
        """Whether this transcript or recording began inside the window.

        An artifact Graph gave no `createdDateTime` for is kept when no window was asked for and
        dropped when one was: it cannot be shown to be the occurrence the caller meant.
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
        """Whether an empty answer for this window means "there is none" rather than "not yet".

        Two independent pieces of evidence, either of which settles it: the window's own end is far
        enough past that anything falling inside it would have landed, or the *meeting* is — the
        second being what answers a caller who asked for no window at all, and what stops a window
        mistakenly set in the future promising an artifact for a meeting that is long over.

        Absent evidence never settles anything: no `started_before` and no `endDateTime` both mean
        nothing says the meeting's artifacts have finished being made, and of the two wrong answers
        the one that costs a caller a second call is the cheaper one.

        A predicate rather than the verdict itself, because the verdict is a different word per
        artifact and the tool that answers owns its own vocabulary — the *inference* is what must
        not exist twice.
        """
        now = datetime.now(UTC)
        return _settled_by(self.started_before, now) or _settled_by(meeting.end_date_time, now)


def as_utc(moment: datetime) -> datetime:
    """`moment` as an aware datetime, reading one that named no timezone as already being UTC.

    Public because the UTC assumption belongs to the window and the window has one home: anything
    comparing or subtracting Graph timestamps resolves them through this and cannot meet a naive
    one.
    """
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


async def resolve_meeting(
    client: GraphServiceClient, handle: MeetingHandle
) -> OnlineMeeting | None:
    """The meeting whose stored `joinWebUrl` is `handle`'s, or None if Graph matched none.

    One request, spending `MEETING_PERMISSION`, and the `$filter` above must exist exactly once —
    see the module docstring for the encoding bug class it sits on top of.

    Graph documents this filter as returning "a collection that contains only one onlineMeeting
    object", and no match as `200 OK` with an empty `value` rather than a 404 — so None here is an
    answer and never an error.
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
    """The `limit` newest artifacts of a meeting that fall inside `window`, newest first.

    **Newest first is a property of what was read, not of the page Graph chose to answer with.**
    Graph documents no `$orderby` on either collection, so it answers in an order of its own; a
    walk that stopped at `limit` and sorted afterwards would return an arbitrary `limit` artifacts
    sorted among themselves, which is the opposite of what "the latest transcript of this series"
    asks for and is undetectable — the answer looks exactly like the right one. So the walk keeps
    everything the window holds, sorts, and only then cuts to `limit`.

    **What was read is the collection up to `MAX_ARTIFACT_SCAN` artifacts, and no further.** That
    bound is where the promise stops being "the newest of this meeting" and starts being "the
    newest of the artifacts read": for a collection no larger than the cap the two coincide, which
    is every meeting bar a daily series recorded for most of a year, and past it the artifacts
    never read are in Graph's arbitrary order and can hold a newer one. Nothing in this function
    can close that gap — with no `$orderby`, the only way to know the newest is to read everything,
    and the cap exists because a collection with no documented ceiling must not turn one tool call
    into an unbounded walk. So the gap is not hidden: it is what `capped` means below, and every
    description over a lister is worded to the prefix rather than to the collection.

    **`capped` means the scan stopped at the cap, and nothing else.** The tempting second meaning
    is "the window held more than `limit`", which is a different fact with the opposite remedy —
    raise `limit` for that one, nothing at all for this one — and a caller told only "there is
    more" cannot tell which it was told, so it has to be warned that the first entry may not be the
    meeting's latest even in the ordinary case. The ordinary case is what the returned count
    already says (a full `limit` may have more behind it), so it is left there rather than merged
    in, and what comes back is the cap alone: the one thing a caller cannot see and the one with no
    remedy. A lister's absence verdict reads it for the same reason, an absence over a prefix being
    no absence.
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
    """The earliest instant `bound` includes, or None where there is no bound."""
    if bound is None:
        return None
    # `datetime` subclasses `date`, so this order is the whole of the distinction.
    if isinstance(bound, datetime):
        return as_utc(bound)
    return datetime.combine(bound, time.min, tzinfo=UTC)


def _last_instant(bound: date | datetime | None) -> datetime | None:
    """The latest instant `bound` includes, or None where there is no bound."""
    if bound is None:
        return None
    if isinstance(bound, datetime):
        return as_utc(bound)
    return datetime.combine(bound, time.max, tzinfo=UTC)


def _settled_by(moment: datetime | None, now: datetime) -> bool:
    """Whether `moment` is far enough past that an artifact belonging to it would have arrived."""
    return moment is not None and as_utc(moment) + ARTIFACT_DELAY_ALLOWANCE < now


def _began_at(artifact: MeetingArtifact) -> datetime:
    """The sort key: when the artifact began, or the beginning of time where Graph did not say.

    Aware for the same reason `OccurrenceWindow.holds` is — one naive value among aware ones makes
    the sort itself raise, which is a crash in the middle of an answer that was already complete.
    """
    began = artifact.created_date_time
    return as_utc(began) if began is not None else datetime.min.replace(tzinfo=UTC)
