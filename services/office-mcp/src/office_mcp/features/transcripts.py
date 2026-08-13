"""Meeting transcripts: from a meeting chat to speaker-attributed, timestamped turns.

This is the one surface where a delegated connector can answer better than a link. Microsoft's own
M365 connector reaches a transcript only through an opaque URI obtained from a calendar read and
returns whatever that yields; the chain here ends in `/transcripts/{id}/content`, which Graph
answers with WebVTT carrying `<v Speaker>` voice tags and cue timestamps — who said what, when.

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
class outcome here rather than an impossible one: `list_chats` reports no `meeting_uri` for that
chat, and there is no fallback, because there is no documented second route. `onlineMeeting` does
carry a `chatInfo.threadId`, and a `$filter` on it would be exactly the invented path this module
refuses to ship: Graph documents neither that property as filterable nor any lookup by it.

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
   would produce `%2525…` and, again, an empty `value`. `test_transcripts.py` pins the bytes that
   reach the wire, because this is the failure that looks like an answer.

`200 OK` with `value: []` is Graph's documented "no match" for this filter — it never 404s — so it
is reported as its own outcome and not as an error.

## The occurrence window, and the shapes a model actually sends

`started_after`/`started_before` exist for one reason: a recurring series is a single meeting to
Graph, so its occurrences share one transcript collection and the only thing telling them apart is
when transcription began. That makes the window the thing a model reaches for most, and it arrives
in whatever shape the model wrote — `2026-08-11T09:00:00+02:00`, but just as often
`2026-08-11T09:00:00` or `2026-08-11`, because that is how a date gets written when nobody is
watching. All three are accepted and resolved against UTC, in `OccurrenceWindow` and nowhere else:
Graph timestamps every transcript in UTC, so UTC is the assumption that needs no second piece of
information, and resolving once at the edge of the module is what stops anything downstream
comparing a naive datetime with an aware one — which is a `TypeError` raised at a caller who did
nothing wrong, not a wrong answer it could notice. A bare date is a whole UTC day rather than its
first instant, because writing the same date in both bounds is how one occurrence gets bracketed and
midnight-to-midnight would be an empty window reported as an answer. The assumption is stated in
each parameter's own description, where a model reads it: `09:00` is a different instant in Zurich,
and a window quietly built in the wrong zone is worse than one that was refused.

## Newest first, exactly as far as it is true

"The latest transcript of this series" is the question this tool exists for, so the order has to be
a property of what was *read* and not of the page Graph happened to answer with — Graph documents
`$select`, `$filter` and `$top` on this collection and no `$orderby` at all
(https://learn.microsoft.com/en-us/graph/api/onlinemeeting-list-transcripts), and a walk that
stopped at `limit` before sorting would return an arbitrary `limit` transcripts sorted among
themselves and call them the newest. That is a wrong answer with the shape of a right one.
`newest_in_window` is where the sort and the cut happen in that order, for both artifacts.

What the promise is worth is bounded by `MAX_ARTIFACT_SCAN`, and every sentence a model reads is
worded to that bound rather than to "the newest of this meeting". Up to that many artifacts are
read, in whatever order Graph chose; for a meeting with no more than that they are the whole
collection and the first entry is the latest outright, which covers every meeting but a series
recorded daily for the better part of a year. Past it the first entry is the newest of the
artifacts that were *read*, a newer one can sit in the part that was not, and `truncated` is true.
Raising the cap would move that boundary rather than remove it: with no `$orderby` to ask the
newest for, nothing short of reading the whole collection makes the word exact, and Graph publishes
no ceiling on how large that collection can be.

## Four failures a caller must act on differently

`GET …/transcripts` returning nothing is not one answer but three, and the tenant switch is a
fourth:

* **`GraphAccessToTranscriptsDisabled`** — a `403` whose remedy names a Teams administrator, not a
  Graph permission. Microsoft Graph access to transcripts is off by default and "no app can access
  meeting transcripts, regardless of app-level permissions"; there is "no request-side workaround".
  It is recognised by inner code in `server/errors.py`, where every other refusal is worded.
* **No transcript** — the meeting was never recorded or never transcribed. Retrying is pointless.
* **Not ready yet** — nothing has landed for the window asked about and something still might.
  Retrying is the *only* thing that helps, which is why this must never be reported as the case
  above — and, just as importantly, why the case above must not be reported as this one: a window
  that has demonstrably passed is answered `not_transcribed` even for a series still running, or a
  model is sent back to poll for an occurrence that ended last month. Graph publishes no status for
  availability and no latency SLA, so both halves are an inference over one generous allowance;
  `OccurrenceWindow.settled` is the whole of it and `MeetingTranscripts.status` admits it as one.
* **Not known** — the walk hit `MAX_ARTIFACT_SCAN` before the collection ended, so the transcripts
  it did not reach might hold the one asked for. Neither absence verdict above is available here:
  both assert something about a collection that was not read to the end, and the caller cannot tell
  from the outside. `scan_incomplete` is that answer, and it is exactly the case where `truncated`
  is true — an answer saying both "there is more" and "there is none" is one no caller can act on.
  It is also the one answer here with **no remedy**, and every place it is described says so. The
  window is applied to the artifacts *after* they are read: Graph documents no filterable date on
  either collection — the one filterable property either reference shows by example is
  `contentCorrelationId` (https://learn.microsoft.com/en-us/graph/api/calltranscript-get, Example
  11) — so the request is bare and the same `MAX_ARTIFACT_SCAN` artifacts are read whatever window
  is asked for. "Narrow `started_after`/`started_before` and ask again" was therefore advice a model
  could follow forever without progress: the next call reads the same artifacts and answers the same
  way. That is the defect class the channel browser already paid for with its circular reply advice,
  and the fix is the same one — a dead end stated plainly beats an actionable-sounding loop, so what
  a caller is told is to stop and report that it is not known.

`SpeakerAttributionNotAllowed` is a fifth Graph answer and the one this module handles rather than
reports: a tenant may permit transcripts and forbid speaker names, and the documented response is
to ask again for the unattributed format. That degrades the answer instead of losing it, and
`Transcript.speaker_attribution` says which one came back.

## What `recordings` borrows from here, and why it is a separate module

A meeting's recordings are answered by `features/recordings.py`, which takes `MeetingHandle`,
`resolve_meeting`, `OccurrenceWindow`, `newest_in_window` and `as_utc` from here: this module owns
the meeting handle family (layering rule 9), so the join URL, the escaping, the window and the order
the artifacts come back in have exactly one home whichever artifact is being asked about. What it
does not share is the outcome word — "was not transcribed" and "was not recorded" are different
facts — or the refusal above, which Microsoft scopes to transcripts alone. That asymmetry is why the
two artifacts are two tools; `features/recordings.py` argues it where the decision was made.
"""

import html
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol, Self
from urllib.parse import quote, unquote

from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.call_transcript import CallTranscript
from msgraph.generated.models.online_meeting import OnlineMeeting
from msgraph.generated.users.item.online_meetings.online_meetings_request_builder import (
    OnlineMeetingsRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import (
    CollectedItems,
    GraphCollection,
    GraphForbidden,
    collect_pages,
    graph_errors,
)

# Resolving a join URL to a meeting is `OnlineMeetings.Read`, the least privilege Graph documents
# for the filter, and needs no admin consent. Reading a transcript is a different, admin-consented
# permission — and a tenant can grant one and withhold the other, which is why they are named
# separately and why the two tools over them exchange different tokens.
MEETING_PERMISSION = "OnlineMeetings.Read"
TRANSCRIPT_PERMISSION = "OnlineMeetingTranscript.Read.All"

# What listing a meeting's transcripts costs: the resolve and the list, in that order, under one
# token. Reading content needs only the second — the handle already carries the resolved meeting id.
LISTING_PERMISSIONS: tuple[str, ...] = (MEETING_PERMISSION, TRANSCRIPT_PERMISSION)

# How many transcripts one listing returns. A one-off meeting has one; a recurring series
# accumulates one per occurrence in the same collection, which is what makes a window necessary at
# all. Graph documents `$top` here but publishes no ceiling, so this is ours.
MAX_TRANSCRIPTS = 50

# How many of a meeting's artifacts one listing may look at, whichever artifact it is. This is what
# "newest first" costs: Graph documents no `$orderby` on either collection, so the newest can only
# be known by looking at the collection, and a walk that stopped at `limit` would be sorting an
# arbitrary handful of it (see `newest_in_window`). The bound is on artifacts rather than on
# requests because that is what `collect_pages` can bound — Graph chooses the page size here and
# publishes none — so the honest statement of the cost is "at most this many artifacts are looked
# at, in however many pages Graph answers them in".
#
# 200 is four times the largest `limit` either lister offers and far past any real meeting: a
# meeting accumulates one artifact per occurrence, so reaching this takes a series that has run
# daily for the better part of a year *and* been recorded every time. A meeting that does exceed it
# is not answered with a guess — the scan is reported as incomplete, no absence is asserted, and
# "newest first" is stated as what it then is, an order over the artifacts that were read.
#
# Raising it is not the fix for either of those, which is why the number is boring: a bigger cap
# moves the boundary and leaves both statements needing the same qualification, because Graph
# offers no `$orderby` to ask the newest for and no date `$filter` to make the window the server's.
MAX_ARTIFACT_SCAN = 200

# How many turns one read returns, and the default window. A turn is one WebVTT cue — a sentence or
# two — so an hour of meeting is some hundreds of them and a 30-hour one (Teams' own limit) is tens
# of thousands. The whole transcript is fetched either way; this bounds what crosses into a model's
# context per call.
MAX_TURNS = 500

# How long after a window closes — or after a meeting ends, where no window was asked for — a
# missing artifact is still called "not ready" rather than "never made". Microsoft publishes no SLA
# and no "processing" status for the availability of a transcript or of a recording, so this is not
# a promise about Graph — it is which of two opposite pieces of advice to give when the evidence is
# the same empty collection. Generous on purpose: telling a caller to wait once when nothing will
# ever arrive costs one call, while telling it a transcript does not exist when it is ten minutes
# away is a wrong answer it cannot detect. Named for artifacts rather than for transcripts because
# `OccurrenceWindow.settled` is what recordings answer their own absence with too.
ARTIFACT_DELAY_ALLOWANCE = timedelta(hours=4)

# The inner code Graph sends when a tenant permits transcripts but forbids speaker names. Branched
# on rather than the message, as Microsoft's own documentation instructs.
_SPEAKER_ATTRIBUTION_REFUSED = "SpeakerAttributionNotAllowed"

# The two formats `/content` serves. VTT is the default and the one worth having — it is the only
# one carrying `<v Speaker>` voice tags. The other is the documented fallback for a tenant with
# speaker attribution switched off, and is selectable *only* by this header ("the
# application/vnd.microsoft.graph.transcript+text format is supported only through this header"),
# which is why neither is requested with `$format`.
_ATTRIBUTED_FORMAT = "text/vtt"
_UNATTRIBUTED_FORMAT = "application/vnd.microsoft.graph.transcript+text"

type _MeetingsQuery = OnlineMeetingsRequestBuilder.OnlineMeetingsRequestBuilderGetQueryParameters


@dataclass(frozen=True, slots=True)
class MeetingHandle:
    """Which meeting, as the only thing a chat can say about one: its join URL.

    A handle rather than a bare URL because a join URL is not an argument a model should be
    composing or re-encoding — Graph warns that "users shouldn't rely on any information extracted
    from parsing the URL" and the `$filter` match is byte-for-byte against what Graph stored.
    Wrapping it means the tool takes something that came from a tool result, and the encoding
    happens in one place.
    """

    join_web_url: str

    @property
    def uri(self) -> str:
        return f"teams:///meetings/{_segment(self.join_web_url)}"


@dataclass(frozen=True, slots=True)
class TranscriptHandle:
    """Which transcript, by the two ids Graph's content path is built from.

    The meeting id and not the join URL, because the resolve has already happened: a reader that
    carried the join URL would repeat it, spend a second Graph request and a second permission, and
    give a 403 that could be about either of them. Graph's own `transcriptContentUrl` is not used —
    the published samples are malformed (`…/transcripts/('…')/content`) — so the path is built from
    the ids, which is what Microsoft's reference shows.
    """

    meeting_id: str
    transcript_id: str

    @property
    def uri(self) -> str:
        return f"teams:///transcripts/{_segment(self.meeting_id)}/{_segment(self.transcript_id)}"


# The two meeting-side handle shapes. Distinct first segments rather than one nested grammar: a
# `teams:///meetings/{x}/transcripts/{y}` would make `{x}` a join URL in one shape and a meeting id
# in the other, and a parser cannot tell those apart.
_MEETING_HANDLE = re.compile(r"\Ateams:///meetings/([^/]+)\Z")
_TRANSCRIPT_HANDLE = re.compile(r"\Ateams:///transcripts/([^/]+)/([^/]+)\Z")


def meeting_handle(uri: str) -> MeetingHandle | None:
    """`uri` as a meeting handle, or None if it is not one.

    None rather than an exception with advice, for the same reason `message_handle` returns None:
    what to tell a caller about a malformed handle is the tool boundary's business.
    """
    match = _MEETING_HANDLE.match(uri)
    if match is None:
        return None
    join_web_url = unquote(match.group(1))
    return MeetingHandle(join_web_url) if join_web_url.strip() else None


def transcript_handle(uri: str) -> TranscriptHandle | None:
    """`uri` as a transcript handle, or None if it is not one."""
    match = _TRANSCRIPT_HANDLE.match(uri)
    if match is None:
        return None
    meeting_id, transcript_id = (unquote(part) for part in match.groups())
    if not meeting_id.strip() or not transcript_id.strip():
        return None
    return TranscriptHandle(meeting_id, transcript_id)


def meeting_uri_for(join_web_url: str | None) -> str | None:
    """A meeting handle for `join_web_url`, or None when Graph gave none.

    Public so that `chats` can put a transcript route on a meeting chat without spelling a handle:
    the grammar has one home per family, and this is the meeting family's.
    """
    if join_web_url is None or not join_web_url.strip():
        return None
    return MeetingHandle(join_web_url).uri


def _segment(value: str) -> str:
    return quote(value, safe="")


class MeetingArtifact(Protocol):
    """The one property a window needs of a meeting artifact: when it began.

    Structural rather than nominal because there are two of these and they are unrelated generated
    classes: `callTranscript` and `callRecording` both carry `createdDateTime` and nothing else
    below is read. Naming the protocol instead of one of them is what lets recordings scope a
    recurring series with the same window rather than with a second implementation of it.
    """

    @property
    def created_date_time(self) -> datetime | None: ...


@dataclass(frozen=True, slots=True)
class OccurrenceWindow:
    """Which occurrence was asked about, as two instants that are always timezone-aware.

    A type rather than two arguments threaded through, because the window decides two things that
    have to agree: which transcripts are kept, and — when none are — whether an empty answer means
    "wait" or "there is none". Reading the second off the *meeting* instead was a wrong answer no
    caller could detect: a recurring series whose `endDateTime` is in the future (or absent) made
    every empty window "still processing", including one bracketing an occurrence that ended weeks
    ago and was never transcribed, which is an instruction to poll forever.

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
        artifact and each lister owns its own vocabulary — the *inference* is what must not exist
        twice.
        """
        now = datetime.now(UTC)
        return _settled_by(self.started_before, now) or _settled_by(meeting.end_date_time, now)


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


def as_utc(moment: datetime) -> datetime:
    """`moment` as an aware datetime, reading one that named no timezone as already being UTC.

    Public because the UTC assumption belongs to the window and the window has one home: anything
    comparing or subtracting Graph timestamps — here, or in the recordings lister deriving a
    duration from two of them — resolves them through this and cannot meet a naive one.
    """
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def _settled_by(moment: datetime | None, now: datetime) -> bool:
    """Whether `moment` is far enough past that an artifact belonging to it would have arrived."""
    return moment is not None and as_utc(moment) + ARTIFACT_DELAY_ALLOWANCE < now


class TranscriptSummary(BaseModel):
    uri: str = Field(
        description=(
            "A handle for this transcript. Pass it verbatim to read_transcript, which is the only "
            + "route to the words that were said — nothing here contains any of them."
        )
    )
    transcript_id: str = Field(
        description="The transcript's Graph id. Identify a transcript by `uri`, not by this alone."
    )
    started_at: datetime | None = Field(
        description=(
            "When transcription began (Microsoft's `createdDateTime`). For a recurring meeting "
            + "this is what tells one occurrence from another: every occurrence's transcript lands "
            + "in the same collection, and Microsoft gives no occurrence id."
        )
    )
    ended_at: datetime | None = Field(
        description="When transcription ended (Microsoft's `endDateTime`)."
    )
    content_correlation_id: str | None = Field(
        description=(
            "Microsoft's identifier linking this transcript to the recording of the same call. "
            + "Nothing here fetches recordings; it is returned because it is the exact link, and "
            + "two transcripts sharing it are two views of one call rather than of two."
        )
    )


class MeetingTranscripts(BaseModel):
    status: str = Field(
        description=(
            "What was found, and therefore what to do next. Exactly one of:\n"
            + "- `available` — `transcripts` lists them; read one.\n"
            + "- `not_ready` — nothing is there for the window you asked about and something may "
            + "still arrive: that window has only just closed, or you asked for no window and the "
            + "meeting itself has not ended or ended recently. Microsoft publishes no availability "
            + "SLA and no 'processing' status, so this is inferred: it means wait and ask again "
            + "later, and it is NOT evidence that no transcript will ever exist. A window that has "
            + "demonstrably passed is never reported this way, however far in the future a "
            + "recurring series runs.\n"
            + "- `not_transcribed` — the window is over, nothing is there, and nothing is "
            + "expected: it was not recorded or transcribed. Retrying will not change this. One "
            + "other cause looks identical and cannot be distinguished: Microsoft's "
            + "meeting-artifact APIs stop serving a meeting once it expires (about 60 days after a "
            + "one-off), so a transcript that once existed can read as never having existed.\n"
            + "- `scan_incomplete` — this meeting has more transcripts than one call reads "
            + f"({MAX_ARTIFACT_SCAN}) and none of the ones read fall in your window, so whether "
            + "one exists there is NOT known and is not being claimed either way. There is nothing "
            + "to try: the window is applied to the transcripts after Microsoft has answered, not "
            + "by Microsoft while answering, so changing `started_after`/`started_before` — "
            + "narrower, wider, anything — reads the same transcripts and returns this same "
            + "status. Stop, and report that whether a transcript exists for that occurrence could "
            + "not be determined. Never report this as 'there is no transcript', and do not ask "
            + "again. `truncated` is true for the same reason.\n"
            + "- `meeting_not_found` — Microsoft matched the join URL to no meeting this user can "
            + "see. Not an error and not proof the meeting is gone; a meeting created outside a "
            + "calendar, or one this user was never invited to, answers the same way. Do not retry "
            + "and do not rebuild the handle."
        )
    )
    meeting_id: str | None = Field(
        description=(
            "The resolved meeting's Graph id, or null when `status` is `meeting_not_found`. "
            + "Opaque, and no tool here takes it — a transcript's `uri` already carries it."
        )
    )
    subject: str | None = Field(
        description=(
            "The meeting's subject as Microsoft holds it, which is how to confirm this is the "
            + "meeting that was meant. It may differ from the chat's topic."
        )
    )
    meeting_type: str | None = Field(
        description=(
            "`scheduled`, `recurring`, `adhoc`, `meetNow`, `broadcast`, or null when Microsoft did "
            + "not say. `recurring` is the one to act on: a whole series is ONE meeting to "
            + "Microsoft, so every occurrence's transcript is in this one collection and "
            + "`started_after`/`started_before` are how to reach a single occurrence."
        )
    )
    started_at: datetime | None = Field(
        description=(
            "When the meeting starts. For a recurring series this is Microsoft's single value for "
            + "the whole series, not the occurrence you asked about."
        )
    )
    ended_at: datetime | None = Field(
        description="When the meeting ends, on the same caveat as `started_at`."
    )
    transcripts: list[TranscriptSummary] = Field(
        description=(
            "The transcripts of this meeting that fall inside the requested window, newest first. "
            + "The order is over every transcript this call read rather than over one page of "
            + f"Microsoft's answer, and one call reads up to {MAX_ARTIFACT_SCAN} of them. For a "
            + "meeting with no more transcripts than that — every meeting bar a series recorded "
            + "daily for most of a year — those are all of them, so the first entry is the latest "
            + "transcript of the window outright, which for a recurring series is how to reach the "
            + "most recent occurrence. Past that cap the first entry is the latest of what was "
            + "READ: Microsoft returns this collection in an order of its own and offers no way to "
            + "ask for the newest, so a newer transcript can sit among the ones never read. "
            + "`truncated` is true whenever that happened. Empty for every status other than "
            + "`available`."
        )
    )
    truncated: bool = Field(
        description=(
            "True when there is more — the same 'there is more' flag every list-shaped tool here "
            + "reports. Two things set it, and they differ in what you may conclude:\n"
            + "- The window holds more transcripts than this `limit`. The ones here are still the "
            + f"newest of the window; raise `limit`, up to {MAX_TRANSCRIPTS}.\n"
            + "- The meeting has more transcripts in total than one call reads "
            + f"({MAX_ARTIFACT_SCAN}). Then `transcripts` is ordered over the ones read and not "
            + "over the meeting, so the first entry may not be the meeting's latest, and no "
            + "argument to this tool reads further — the window is applied after the read, so "
            + "narrowing it changes nothing.\n"
            + "Which of the two happened is not always visible, so do not call the first entry the "
            + "meeting's most recent transcript while this is true unless you say it is the most "
            + "recent of what was read. Fewer entries than you asked for with this true is always "
            + "the second case. There is no cursor. When this is true and nothing came back, "
            + "`status` is `scan_incomplete` and no absence is claimed."
        )
    )


class TranscriptTurn(BaseModel):
    speaker: str | None = Field(
        description=(
            "Who spoke, as Teams attributed them. Null when this transcript has no speaker "
            + "attribution at all (see `speaker_attribution`) and null for the occasional turn "
            + "Microsoft attributed to nobody — a null is not an unidentified person."
        )
    )
    start_seconds: float = Field(
        description=(
            "When this turn starts, in seconds from the beginning of transcription — not from the "
            + "start of the meeting, and not a wall-clock time. Add it to the transcript's "
            + "`started_at` for that. It can be NEGATIVE: Microsoft documents negative offsets as "
            + "meaning transcription began while the conversation was already under way."
        )
    )
    end_seconds: float = Field(description="When this turn ends, on the same scale.")
    text: str = Field(description="What was said, with Teams' own cue markup removed.")


class Transcript(BaseModel):
    uri: str = Field(description="The handle this transcript was read by, echoed back.")
    meeting_id: str = Field(description="The meeting this transcript belongs to.")
    transcript_id: str = Field(description="The transcript's Graph id.")
    speaker_attribution: bool = Field(
        description=(
            "True when Microsoft named the speakers, which is the normal case. False when this "
            + "tenant has speaker attribution switched off: the words and the timings are all "
            + "still here and every `speaker` is null. Do not guess who spoke from the content, "
            + "and say so if the answer depends on who said something."
        )
    )
    turns: list[TranscriptTurn] = Field(
        description=(
            "What was said, in order, one turn per utterance Microsoft timestamped — the turns "
            + "matching `from_seconds`, `to_seconds` and `speaker` where any of those was given, "
            + "and every turn of the transcript where none was. Empty means nothing matched what "
            + "was asked for, which is not the same as the meeting having no words in it."
        )
    )
    truncated: bool = Field(
        description=(
            "True when more turns match than this page holds — the same 'there is more' flag every "
            + "list-shaped tool here reports. It is counted over the turns left after "
            + "`from_seconds`, `to_seconds` and `speaker` were applied, so 'there is more' always "
            + "means more of what was asked for rather than more of the meeting. Pass "
            + "`next_offset` back as `offset` to continue. Never summarise a truncated transcript "
            + "as the whole meeting."
        )
    )
    next_offset: int | None = Field(
        description=(
            "The `offset` that reaches the next matching turns, or null when `truncated` is false. "
            + "It indexes the turns the filters kept, so send the same `from_seconds`, "
            + "`to_seconds` and `speaker` with it — changing one of them renumbers what it points "
            + "at."
        )
    )


async def list_meeting_transcripts(
    client: GraphServiceClient,
    *,
    handle: MeetingHandle,
    started_after: date | datetime | None,
    started_before: date | datetime | None,
    limit: int,
) -> MeetingTranscripts:
    """The transcripts of the meeting `handle` addresses, and what a caller should do about them.

    Two Graph requests at most: resolve the join URL, then list. The listing goes out bare, and the
    window is applied while paging it rather than as a `$filter`: Graph advertises `$select`,
    `$filter` and `$top` here and no `$orderby`, and the only filterable property either artifact's
    reference shows is `contentCorrelationId`
    (https://learn.microsoft.com/en-us/graph/api/calltranscript-get, Example 11) — never a date. So
    a server-side date bound is unverified, and a wrong one returns `200 OK` with nothing rather
    than failing. That is also why the window is no help to a caller whose scan stopped short: it
    is ours, applied to what came back, so it cannot make Graph send different artifacts.

    The bounds are whatever the caller passed — `OccurrenceWindow.of` is what makes them instants —
    and the same window then decides both which transcripts are kept and what an empty answer means.
    """
    assert 1 <= limit <= MAX_TRANSCRIPTS, f"limit must be within 1..{MAX_TRANSCRIPTS}, got {limit}"
    window = OccurrenceWindow.of(started_after, started_before)

    with graph_errors():
        meeting = await resolve_meeting(client, handle)
        if meeting is None or meeting.id is None:
            return MeetingTranscripts(
                status="meeting_not_found",
                meeting_id=None,
                subject=None,
                meeting_type=None,
                started_at=None,
                ended_at=None,
                transcripts=[],
                truncated=False,
            )
        first_page = await client.me.online_meetings.by_online_meeting_id(
            meeting.id
        ).transcripts.get()
        assert first_page is not None, "Graph answered a transcript listing with no collection"
        collected = await newest_in_window(first_page, client, window=window, limit=limit)

    found = collected.items
    return MeetingTranscripts(
        status="available"
        if found
        else _absence(scan_stopped_short=collected.truncated, settled=window.settled(meeting)),
        meeting_id=meeting.id,
        subject=meeting.subject,
        # `OnlineMeetingBase.meetingType` is a generated enum subclassing `str`, so the member is
        # its own wire value; a value the SDK predates deserializes to None rather than raising.
        meeting_type=meeting.meeting_type,
        started_at=meeting.start_date_time,
        ended_at=meeting.end_date_time,
        transcripts=[_summary(meeting.id, transcript) for transcript in found],
        truncated=collected.truncated,
    )


def _absence(*, scan_stopped_short: bool, settled: bool) -> str:
    """Which empty answer to give: the one that means stop, the one that means wait, or neither.

    A scan that stopped short is checked first, and it is the whole of the second fix here: the
    walk having been cut means the artifacts it did not reach might hold the one asked for, so
    nothing about absence is known — and "not transcribed / retrying will not help" is exactly the
    assertion that must not be made. Reported instead as `scan_incomplete`, alongside the
    `truncated: true` that comes from the same value, so that "there is more" and "there is none"
    can never both be said of one answer.

    It is also the one verdict here that offers a caller nothing to do, and its description says so
    in as many words: the window is applied after the artifacts are read, so no window sends the
    next call further into the collection. The advice is to stop and report the uncertainty, which
    is the only advice that is true — see the module docstring's fourth failure.

    Otherwise the evidence is `OccurrenceWindow.settled` and the word is this module's, because a
    meeting that was recorded but not transcribed is answered `not_transcribed` here and
    `available` by the recordings lister — the same evidence about two different artifacts.
    """
    if scan_stopped_short:
        return "scan_incomplete"
    return "not_transcribed" if settled else "not_ready"


async def resolve_meeting(
    client: GraphServiceClient, handle: MeetingHandle
) -> OnlineMeeting | None:
    """The meeting whose stored `joinWebUrl` is `handle`'s, or None if Graph matched none.

    Public because every meeting-side feature needs it and the `$filter` below must exist once:
    this module owns the meeting handle family, so it owns the one request that redeems a handle.
    Its permission is `MEETING_PERMISSION`, which is why the two travel together.

    The filter is built with the join URL doubled-quote-escaped and otherwise untouched: the SDK
    percent-encodes a query parameter's value on expansion, which is precisely the single encoding
    Graph's note requires, and doing it here as well would send `%2525…`.

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


def _began_at(artifact: MeetingArtifact) -> datetime:
    """The sort key: when the artifact began, or the beginning of time where Graph did not say.

    Aware for the same reason `OccurrenceWindow.holds` is — one naive value among aware ones makes
    the sort itself raise, which is a crash in the middle of an answer that was already complete.
    """
    began = artifact.created_date_time
    return as_utc(began) if began is not None else datetime.min.replace(tzinfo=UTC)


async def newest_in_window[T: MeetingArtifact](
    first_page: GraphCollection[T],
    client: GraphServiceClient,
    *,
    window: OccurrenceWindow,
    limit: int,
) -> CollectedItems[T]:
    """The `limit` newest artifacts of a meeting that fall inside `window`, newest first.

    Shared by both meeting listers, and the reason it is one function rather than four lines
    written twice: the order, the bound and the meaning of `truncated` are the same promise about
    two artifacts, and the two got it wrong the same way.

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
    into an unbounded walk. So the gap is not hidden: it is what the second `truncated` cause
    below means, and every description over these two listers is worded to the prefix rather than
    to the collection.

    **`truncated` means "there is more", and both ways of there being more set it**: matching
    artifacts older than the ones returned, and a collection larger than the scan cap. The second
    is the case in which the order is only over the prefix, and the same case in which an empty
    answer proves nothing — which is why the flag and the verdict are read from the same value; see
    `_absence` in each lister.
    """
    collected = await collect_pages(
        first_page,
        client,
        limit=MAX_ARTIFACT_SCAN,
        matches=window.holds,
        max_scanned=MAX_ARTIFACT_SCAN,
    )
    newest = sorted(collected.items, key=_began_at, reverse=True)
    return CollectedItems(
        items=newest[:limit], truncated=collected.truncated or len(newest) > limit
    )


def _summary(meeting_id: str, transcript: CallTranscript) -> TranscriptSummary:
    assert transcript.id is not None, "Graph returned a transcript with no id"
    return TranscriptSummary(
        uri=TranscriptHandle(meeting_id, transcript.id).uri,
        transcript_id=transcript.id,
        started_at=transcript.created_date_time,
        ended_at=transcript.end_date_time,
        content_correlation_id=transcript.content_correlation_id,
    )


async def read_transcript(
    client: GraphServiceClient,
    *,
    handle: TranscriptHandle,
    offset: int,
    limit: int,
    from_seconds: float | None = None,
    to_seconds: float | None = None,
    speaker: str | None = None,
) -> Transcript:
    """The turns of one transcript matching the filters, from `offset`, up to `limit` of them.

    One Graph request, or two where the tenant refuses speaker attribution. Paging is over the
    parsed turns rather than over Graph — `/content` is a single stream with no ranged contract —
    so a later page costs the same fetch again, which is what makes `limit` worth widening rather
    than looping. The filters are the same bargain: the whole transcript is fetched and parsed
    whatever they are, so they make the answer smaller and never the call cheaper.

    They are applied *before* the page is cut, and `truncated`/`next_offset` are counted over what
    they left. That is the only version of "there is more" a caller can act on: paging the whole
    transcript while filtering each page would make the flag mean "more of the meeting" while the
    turns meant "the ones you asked for", and a caller following `next_offset` to the end would
    walk pages that hold nothing.
    """
    assert 1 <= limit <= MAX_TURNS, f"limit must be within 1..{MAX_TURNS}, got {limit}"
    assert offset >= 0, f"offset must not be negative, got {offset}"
    assert from_seconds is None or to_seconds is None or from_seconds <= to_seconds, (
        f"from_seconds must not be after to_seconds, got {from_seconds} and {to_seconds}"
    )

    # TODO: every page refetches and reparses the whole transcript, because `/content` has no
    # ranged contract. Caching the parsed turns per handle is the fix.
    content, attributed = await _content(client, handle)

    turns = _matching(
        _turns(content, attributed=attributed),
        from_seconds=from_seconds,
        to_seconds=to_seconds,
        speaker=speaker,
    )
    page = turns[offset : offset + limit]
    truncated = offset + len(page) < len(turns)
    return Transcript(
        uri=handle.uri,
        meeting_id=handle.meeting_id,
        transcript_id=handle.transcript_id,
        speaker_attribution=attributed,
        turns=page,
        truncated=truncated,
        next_offset=offset + len(page) if truncated else None,
    )


def _matching(
    turns: list[TranscriptTurn],
    *,
    from_seconds: float | None,
    to_seconds: float | None,
    speaker: str | None,
) -> list[TranscriptTurn]:
    """The turns of `turns` that all of the given filters keep, in the order they were said.

    **The time test is overlap, and both bounds are inclusive.** A turn is one utterance of a
    sentence or two, and the moment a caller asks about lands in the middle of one about as often
    as it lands between two — so a turn that straddles a bound is kept whole rather than dropped or
    cut. Comparing a turn's *start* to both bounds instead would silently lose the sentence already
    under way at `from_seconds`, which is exactly the sentence that says what the stretch is about.

    **The speaker test is a case-insensitive substring of the display name.** A model asking about
    a person has a name it read somewhere, not the string Teams stores, and those differ by case,
    by a middle name, by a title or by the parenthesised suffix a tenant appends. An exact match
    would answer "that person said nothing" to a spelling difference.

    A turn Microsoft attributed to nobody never matches a speaker filter: `speaker` is null there,
    and there is nothing to compare. Neither does *any* turn of a transcript from a tenant with
    speaker attribution switched off, where every `speaker` is null by construction — this is not
    refused and not degraded to "everything", because a filter that quietly stopped filtering would
    be worse than an empty answer. `Transcript.speaker_attribution` is the flag that explains that
    answer, and every description over this argument says to read the two together.
    """
    wanted = speaker.casefold() if speaker is not None else None
    return [
        turn
        for turn in turns
        if (from_seconds is None or turn.end_seconds >= from_seconds)
        and (to_seconds is None or turn.start_seconds <= to_seconds)
        and (wanted is None or (turn.speaker is not None and wanted in turn.speaker.casefold()))
    ]


async def _content(client: GraphServiceClient, handle: TranscriptHandle) -> tuple[bytes, bool]:
    """The transcript's bytes, and whether they carry speaker names.

    The attributed format is asked for first because it is the one worth having and the default. The
    single retry is Graph's own documented remedy for a tenant that permits transcripts and forbids
    speaker names — "Retry the same request asking for the unattributed format … which succeeds" —
    and it is scoped to that inner code alone: the tenant-wide switch reports itself the same way
    (`403 Forbidden`) and has no request-side workaround, so retrying it would be one wasted call
    and a message about the wrong remedy.

    Each attempt gets its own `graph_errors` rather than one around both. The branch is on a
    *classified* failure — the SDK's raw `APIError` has no inner code on it — so the translation has
    to have happened before the `except` can decide anything, which a block enclosing the whole
    function would defer until after it had already given up.
    """
    endpoint = (
        client.me.online_meetings.by_online_meeting_id(handle.meeting_id)
        .transcripts.by_call_transcript_id(handle.transcript_id)
        .content
    )
    try:
        with graph_errors():
            attributed = await endpoint.get(
                request_configuration=RequestConfiguration(headers=_accepting(_ATTRIBUTED_FORMAT))
            )
    except GraphForbidden as refusal:
        if refusal.inner_code != _SPEAKER_ATTRIBUTION_REFUSED:
            raise
        with graph_errors():
            unattributed = await endpoint.get(
                request_configuration=RequestConfiguration(headers=_accepting(_UNATTRIBUTED_FORMAT))
            )
        return (unattributed or b"", False)
    return (attributed or b"", True)


def _accepting(media_type: str) -> HeadersCollection:
    """A `HeadersCollection` of our own asking for `media_type`.

    Built per request: `RequestConfiguration.headers` defaults to one instance shared by every
    configuration in the process, so adding to the default would add to every other Graph request
    this connector makes. The generated builder adds its own `Accept` with `try_add`, which is a
    no-op once this one is present — which is how a format gets selected at all.
    """
    headers = HeadersCollection()
    headers.add("Accept", media_type)
    return headers


# One WebVTT cue's timing line. The hours field is optional in WebVTT and Teams omits it in some
# transcripts; the leading sign is what Microsoft's "negative offsets" note requires.
_TIMESTAMP = r"-?(?:\d+:)?\d{1,2}:\d{1,2}[.,]\d{1,3}"
_CUE_TIMING = re.compile(rf"^(?P<start>{_TIMESTAMP})\s*-->\s*(?P<end>{_TIMESTAMP})")

# A voice span, which is where a speaker's name lives: `<v Ada Lovelace>text</v>`. The class suffix
# (`<v.loud Ada>`) is part of WebVTT and Teams may emit it.
_VOICE = re.compile(r"<v(?:\.[^\s>]+)?\s+(?P<speaker>[^>]*)>(?P<said>.*?)(?:</v>|\Z)", re.DOTALL)

# Every other cue-payload tag: `<i>`, `<c.colorE5E5E5>`, `<00:00:01.000>` timestamps, `<lang en>`.
_MARKUP = re.compile(r"<[^>]*>")

_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def _turns(content: bytes, *, attributed: bool) -> list[TranscriptTurn]:
    """`content` as speaker-attributed, timestamped turns.

    One cue is one turn: Teams emits an utterance per cue, so merging them would be inventing a
    grouping Microsoft did not make. Anything that is not a cue — the `WEBVTT` header, `NOTE`,
    `STYLE` and `REGION` blocks, a cue identifier line — is skipped rather than guessed at, and a
    cue with a timing line but no words is dropped: an empty turn reads as a silence somebody sat
    through.

    `attributed` is what the request asked for, and it decides whether an unparsed `<v …>` could
    have been there at all — the unattributed format has none by construction.
    """
    text = content.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    turns: list[TranscriptTurn] = []
    for block in _BLANK_LINE.split(text):
        turn = _turn(block, attributed=attributed)
        if turn is not None:
            turns.append(turn)
    return turns


def _turn(block: str, *, attributed: bool) -> TranscriptTurn | None:
    """One cue block as a turn, or None if it is not a cue (or is one with nothing said)."""
    lines = [line for line in block.split("\n") if line.strip()]
    timing = next(
        ((index, match) for index, line in enumerate(lines) if (match := _CUE_TIMING.match(line))),
        None,
    )
    if timing is None:
        return None
    index, match = timing
    speaker, said = _spoken("\n".join(lines[index + 1 :]), attributed=attributed)
    if not said:
        return None
    return TranscriptTurn(
        speaker=speaker,
        start_seconds=_seconds(match.group("start")),
        end_seconds=_seconds(match.group("end")),
        text=said,
    )


def _spoken(payload: str, *, attributed: bool) -> tuple[str | None, str]:
    """A cue payload as (speaker, words).

    The voice span is read before the markup is stripped, because stripping it first would take the
    speaker's name with it. An attributed transcript whose cue carries no voice span keeps a null
    speaker rather than borrowing the previous turn's: Teams does leave some utterances
    unattributed, and attributing them to whoever spoke last would put words in someone's mouth.
    """
    voice = _VOICE.search(payload) if attributed else None
    speaker = voice.group("speaker").strip() if voice is not None else None
    said = voice.group("said") if voice is not None else payload
    words = html.unescape(_MARKUP.sub("", said)).replace("\xa0", " ")
    return (speaker or None, " ".join(words.split()))


def _seconds(timestamp: str) -> float:
    """A WebVTT timestamp as seconds, keeping its sign.

    `HH:MM:SS.mmm` and `MM:SS.mmm` are both legal; the comma decimal separator is not WebVTT but is
    what SubRip uses and costs nothing to accept.
    """
    negative = timestamp.startswith("-")
    parts = timestamp.lstrip("-").replace(",", ".").split(":")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return -total if negative else total
