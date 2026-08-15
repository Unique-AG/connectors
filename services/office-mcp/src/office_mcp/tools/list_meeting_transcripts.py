"""`list_meeting_transcripts` — whether a Teams meeting was transcribed, and a handle for each.

It says what exists and none of what was said. Two things make that a tool of its own rather than a
field on something larger: a transcript is large, and a recurring series is a single meeting to
Graph — every occurrence's transcript lands in the same collection, distinguished only by when
transcription started — so which occurrence is meant is a decision made from this answer rather than
a default anything can pick.

How a meeting is addressed, how the join URL is escaped onto the wire, what an occurrence window is,
and how far "newest first" is true are all `shared/meetings.py`: they are promises about the meeting
rather than about its transcripts, and this file is only the first tool to need them. The handle
grammar itself is `shared/handles.py`, for the same reason one step further out: the transcript
handle this file mints is what a reader of one parses, and a second speller would look like a handle
one tool produced and another answers 404 to.

Everything else is here — the name, the description, the two permissions, the arguments, the answer
shape, the Graph requests and every refusal only this tool can explain. What is most this file's own
is the *vocabulary of the answer*. "Was not transcribed" is a fact about one artifact of a meeting
and not about the meeting: Microsoft gates a meeting's artifacts independently, so these five words
are this tool's and may never be read as a verdict on the meeting itself.

## Four failures a caller must act on differently

`GET …/transcripts` returning nothing is not one answer but three, and the tenant switch is a
fourth:

* **`GraphAccessToTranscriptsDisabled`** — a `403` whose remedy names a Teams administrator, not a
  Graph permission. Microsoft Graph access to meeting transcripts is off by default and "no app can
  access meeting transcripts, regardless of app-level permissions"; there is "no request-side
  workaround", so re-consent is explicitly ruled out. It is recognised by inner code in
  `shared/seam.py`, where every other refusal is worded. Microsoft scopes the switch to transcript
  resources, so it does **not** cover recordings: a refusal here says nothing about whether the
  meeting was recorded, and this tool must not be read as though it had.
* **No transcript** — the meeting was never recorded or never transcribed. Retrying is pointless.
* **Not ready yet** — nothing has landed for the window asked about and something still might.
  Retrying is the *only* thing that helps, which is why this must never be reported as the case
  above — and, just as importantly, why the case above must not be reported as this one: a window
  that has demonstrably passed is answered `not_transcribed` even for a series still running, or a
  model is sent back to poll for an occurrence that ended last month. Graph publishes no status for
  availability and no latency SLA, so both halves are an inference over one generous allowance;
  `OccurrenceWindow.settled` is the whole of it and `MeetingTranscripts.status` admits it as one.
  `not_ready` and a settled absence are the same empty collection from Graph with opposite advice.
* **Not known** — the walk hit `MAX_ARTIFACT_SCAN` before the collection ended, so the transcripts
  it did not reach might hold the one asked for. Neither absence verdict above is available here:
  both assert something about a collection that was not read to the end, and the caller cannot tell
  from the outside. `scan_incomplete` is that answer — an answer saying both "there is more" and
  "there is none" is one no caller can act on. The sentence it gives a model, "this meeting has more
  transcripts than one call reads", is a claim about the meeting, and it is true only because the
  walk underneath it can no longer stop for any other reason: `graph_client/pagination.py` follows
  an empty page carrying a next link rather than reading it as the end, and refuses a collection
  that answers nothing but empty pages rather than answering short. Without that, a four-transcript
  meeting Graph paged `[3, nothing, 1]` would be told the same thing — which is why this file's
  tests page one that way and assert every transcript comes back.
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

## Newest first is a promise about the collection, not about a page of it

Graph documents `$select`, `$filter` and `$top` on this collection and no `$orderby` at all, so it
answers in an order of its own. The window is therefore taken whole — to the scan cap — ordered, and
only then cut to `limit`. A walk that stopped at `limit` before sorting would return an arbitrary
`limit` transcripts sorted among themselves and call them the newest, which is a wrong answer with
the shape of a right one. `newest_in_window` is where that happens, for whatever lists a meeting's
artifacts.

`include_scan_completeness` is opt-in because it is the only thing here a caller cannot work out for
itself. "The window held more transcripts than your `limit`" it can: a full window may have more
behind it and a short one is all there was, which is what a page size means everywhere. "The read
stopped at the cap" it cannot, and merging the two into one flag would give one name to two facts
with opposite remedies — raise `limit` for the first, nothing at all for the second. Where nothing
came back at all it is not opt-in: `status` is `scan_incomplete`, because an absence asserted over a
collection nobody read to the end is the wrong answer all of this exists to avoid.
"""

from datetime import date, datetime
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.call_transcript import CallTranscript
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import graph_client_for, graph_errors
from office_mcp.shared.handles import MeetingHandle, TranscriptHandle, meeting_handle
from office_mcp.shared.meetings import (
    MAX_ARTIFACT_SCAN,
    MEETING_PERMISSION,
    TRANSCRIPT_PERMISSION,
    OccurrenceWindow,
    newest_in_window,
    resolve_meeting,
)
from office_mcp.shared.seam import READ_ONLY, graph_token, graph_tool_errors

TOOL_NAME = "list_meeting_transcripts"

# Reading a transcript resource is an admin-consented permission, and a different one from the
# resolve that precedes it: a tenant can grant one and withhold the other. Both names come from
# `shared/meetings.py` rather than being typed here — a permission is the resource's, and rule 4
# forbids the next module that reaches the same resource from importing this file to find out how
# it is spelled.
#
# What listing a meeting's transcripts costs: the resolve and the list, in that order, under one
# token — Entra redeems them together or not at all. The handle minted below already carries the
# resolved meeting id, so reading a transcript's content later needs only the second of the two,
# and a tenant that withholds `OnlineMeetings.Read` does not put transcript content out of reach.
GRAPH_PERMISSIONS: tuple[str, ...] = (MEETING_PERMISSION, TRANSCRIPT_PERMISSION)

# Built once at import: a call inside a parameter default rebuilds the descriptor on every
# registration and is a lint error in both of this repo's checkers.
_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

# How many transcripts one listing returns. A one-off meeting has one; a recurring series
# accumulates one per occurrence in the same collection, which is what makes a window necessary at
# all. Graph documents `$top` here but publishes no ceiling, so this is ours.
MAX_TRANSCRIPTS = 50

_DESCRIPTION = f"""\
Find out whether a Teams meeting was transcribed, and get a handle for each transcript. Takes the \
`meeting_uri` that list_chats reports on a meeting chat.

This says what exists and returns none of the words that were said. A recurring meeting is a \
single meeting to Microsoft — every occurrence's transcript lands in the same collection, \
distinguished only by when transcription started — so scope to one occurrence with \
`started_after`/`started_before` when `meeting_type` comes back `recurring`; a one-off meeting has \
a single transcript and needs neither. Both bounds take a date (`2026-08-11`, meaning that whole \
UTC day) or a timestamp, with or without a timezone offset — one without is read as UTC, so pass \
the offset when you are working from a local time.

**Read `status` before anything else. It has five values and they mean five different actions:**
- `available` — transcripts are listed, newest first. "Newest" is over the transcripts this call \
read, which is every transcript the meeting has unless the meeting holds more of them than the cap \
below — set `include_scan_completeness` if the answer turns on that.
- `not_ready` — nothing has landed for the window you asked about and something still might: that \
window has only just closed, or you asked for no window and the meeting has not ended or ended \
recently. Wait and call again later. This is NOT "there is no transcript", and reporting it as one \
is wrong: Microsoft publishes no availability SLA, so this tool infers it from how recently the \
window (or the meeting) ended and errs towards telling you to wait. An occurrence window that is \
already well past never answers this — a series whose end date is in the future does not make a \
last-month occurrence "still processing".
- `not_transcribed` — the window you asked about is over and nothing is there: it was not recorded \
or not transcribed. Retrying will not help. Say the meeting has no transcript rather than that the \
meeting did not happen. (One other cause is indistinguishable: Microsoft stops serving a meeting's \
transcripts once the meeting expires, roughly 60 days after a one-off.)
- `scan_incomplete` — this meeting has more transcripts than one call reads \
({MAX_ARTIFACT_SCAN}) and none of the ones read are in your window, so whether one \
exists there is not known. This is the one answer that claims nothing, and the one with nothing to \
try: the window is applied to the transcripts after Microsoft has answered them, so a narrower \
`started_after`/`started_before` reads the same transcripts and returns this same answer, however \
many times you ask. Stop here. Report that this meeting has too many transcripts to read through \
and that whether the occurrence you meant was transcribed could not be determined — that \
uncertainty is the answer. Never report it as "there is no transcript".
- `meeting_not_found` — Microsoft matched the join URL in the handle to no meeting this user can \
see. Not an error, and not proof the meeting is gone. Do not retry and do not rebuild the handle.

This tool answers about transcripts only. Whether the meeting was RECORDED is a separate question \
that Microsoft gates independently — the tenant setting below blocks transcripts and leaves \
recordings alone — and nothing on this server answers it, so a refusal here is not evidence about \
the meeting's recording either way. No video is returned or reachable anywhere in this connector; \
a transcript is the better artifact for a question about a meeting anyway, being text with who \
said what and when.

Two things can refuse this call outright, and both are somebody's decision rather than a bug. \
Reading transcripts over Microsoft Graph is an organisation-wide Teams setting that is OFF by \
default and that no application can switch on; when it is off, the error says so and names the \
administrator who can change it. Separately, Microsoft documents transcript access under \
{TRANSCRIPT_PERMISSION} without stating that meeting participants get it, so a \
participant may be refused where the meeting's organiser would succeed.\
"""

# What this tool says when its `meeting_uri` is not a meeting handle. Its own text rather than one
# shared with whatever asks about a meeting next: the failure it has to prevent is a caller being
# sent to the wrong tool, and a tool file that borrowed another's refusal would be re-creating a
# tool-declaration module one import at a time (`tests/test_layering.py` rule 4).
_NOT_A_MEETING_HANDLE = (
    "list_meeting_transcripts takes the `meeting_uri` that list_chats reports on a meeting chat, "
    + "and this is not one. A meeting handle has exactly one shape:\n"
    + "  teams:///meetings/{join_web_url}\n"
    + "with the join URL percent-encoded. It cannot be assembled — Microsoft addresses a "
    + "meeting by the join URL of the Teams meeting itself, which only Microsoft can supply — "
    + "so call list_chats, find the `meeting` chat for the meeting in question, and pass its "
    + "`meeting_uri` verbatim. A chat id, a chat topic, a Teams web link and a "
    + "`teams:///transcripts/...` handle are none of them a meeting handle — that last one is "
    + "what this tool produces rather than what it takes. Retrying this value will fail "
    + "identically."
)


class TranscriptSummary(BaseModel):
    uri: str = Field(
        description=(
            "This connector's handle for the transcript: what identifies it across calls, and "
            + "what to quote verbatim when referring to it. Nothing here contains any of the "
            + "words that were said."
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
            + "- `available` — `transcripts` lists them, newest first.\n"
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
            + "again.\n"
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
            + "ask for the newest, so a newer transcript can sit among the ones never read; set "
            + "`include_scan_completeness` when the answer turns on that. As many entries as "
            + "`limit` means the window may hold older ones too — raise `limit`, up to "
            + f"{MAX_TRANSCRIPTS} — and fewer than `limit` means these are the whole window. There "
            + "is no cursor. Empty for every status other than `available`."
        )
    )
    scan_incomplete: bool | None = Field(
        description=(
            "Whether the read stopped at the cap on how many of this meeting's transcripts one "
            + f"call looks through ({MAX_ARTIFACT_SCAN}), or null when "
            + "`include_scan_completeness` was not set — which is the default, because it only "
            + "matters for a meeting with more transcripts than that.\n"
            + "True means `transcripts` is ordered over the ones READ and not over the meeting, so "
            + "the first entry may not be the meeting's latest and nothing here reads further: no "
            + "argument to this tool changes it, the window being applied after the read. False "
            + "means the whole collection was read, so the order and any absence within it are "
            + "exact. This says nothing about `limit` — that the window held more than you asked "
            + "for is what a full `transcripts` list means. You never need this to tell whether an "
            + "empty answer is trustworthy: `status` is `scan_incomplete` in exactly that case."
        )
    )


async def list_meeting_transcripts(
    client: GraphServiceClient,
    *,
    handle: MeetingHandle,
    started_after: date | datetime | None,
    started_before: date | datetime | None,
    limit: int,
    include_scan_completeness: bool,
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

    `include_scan_completeness` decides only whether `scan_incomplete` is reported, never what is
    read: it is the same two requests either way. Off by default because it answers a question
    about one rare meeting shape, and a field that is null for all but that shape is a field a
    model does not have to reason about — while `status` still reports a scan that stopped short
    whenever it is the difference between "there is none" and "nobody looked".
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
                scan_incomplete=False if include_scan_completeness else None,
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
        else _absence(scan_stopped_short=collected.capped, settled=window.settled(meeting)),
        meeting_id=meeting.id,
        subject=meeting.subject,
        # `OnlineMeetingBase.meetingType` is a generated enum subclassing `str`, so the member is
        # its own wire value; a value the SDK predates deserializes to None rather than raising.
        meeting_type=meeting.meeting_type,
        started_at=meeting.start_date_time,
        ended_at=meeting.end_date_time,
        transcripts=[_summary(meeting.id, transcript) for transcript in found],
        scan_incomplete=collected.capped if include_scan_completeness else None,
    )


def _absence(*, scan_stopped_short: bool, settled: bool) -> str:
    """Which empty answer to give: the one that means stop, the one that means wait, or neither.

    A scan that stopped short is checked first, and it is what makes the other two safe to say: the
    walk having been cut means the artifacts it did not reach might hold the one asked for, so
    nothing about absence is known — and "not transcribed / retrying will not help" is exactly the
    assertion that must not be made. Reported instead as `scan_incomplete`, so that "there is more"
    and "there is none" can never both be said of one answer. This is the one place the scan's
    completeness reaches a caller whether or not it was asked for: an empty answer is only worth
    anything with it, whereas the same fact about a non-empty answer is the rare caveat behind
    `include_scan_completeness`.

    It is also the one verdict here that offers a caller nothing to do, and its description says so
    in as many words: the window is applied after the artifacts are read, so no window sends the
    next call further into the collection. The advice is to stop and report the uncertainty, which
    is the only advice that is true — see the module docstring's fourth failure.

    Otherwise the evidence is `OccurrenceWindow.settled` and the word is this tool's, because a
    meeting that was recorded but never transcribed is `not_transcribed` here: the verdict is about
    one artifact of the meeting, never about the meeting.
    """
    if scan_stopped_short:
        return "scan_incomplete"
    return "not_transcribed" if settled else "not_ready"


def _summary(meeting_id: str, transcript: CallTranscript) -> TranscriptSummary:
    assert transcript.id is not None, "Graph returned a transcript with no id"
    return TranscriptSummary(
        uri=TranscriptHandle(meeting_id, transcript.id).uri,
        transcript_id=transcript.id,
        started_at=transcript.created_date_time,
        ended_at=transcript.end_date_time,
        content_correlation_id=transcript.content_correlation_id,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Declare this tool against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` from `create_graph_transport`; the tool
    borrows it per call and never owns it. `create_app` closes it on shutdown.
    """

    @mcp.tool(
        name=TOOL_NAME,
        title="List a Meeting's Transcripts",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def list_transcripts(
        meeting_uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The meeting whose transcripts to list, exactly as list_chats reported "
                    + "`meeting_uri` on a meeting chat: "
                    + "`teams:///meetings/{join_web_url}`. Copy it verbatim — it carries the "
                    + "meeting's join URL, which Microsoft matches character for character, and "
                    + "nothing else identifies a meeting to this connector."
                ),
            ),
        ],
        started_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only transcripts whose transcription began at or after this moment. This is "
                    + "how to reach one occurrence of a recurring meeting, whose occurrences all "
                    + "share a single meeting and therefore a single transcript collection. Three "
                    + "shapes are accepted and none of them fails: `2026-08-11T09:00:00+02:00` (or "
                    + "`...Z`) means the instant it names; `2026-08-11T09:00:00`, which names no "
                    + "offset, IS READ AS UTC; and a bare `2026-08-11` means that whole UTC day, "
                    + "starting at its first instant here. Pass the offset whenever what you know "
                    + "is a local time — 09:00 in Zurich is 07:00Z, and a window built in the "
                    + "wrong zone answers about the wrong hours without saying so. A window with "
                    + "no transcript inside it is an answer and not an error: `not_transcribed` "
                    + "once the window is past, `not_ready` while it is recent."
                )
            ),
        ] = None,
        started_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only transcripts whose transcription began at or before this moment. Pair it "
                    + "with `started_after` to bracket one occurrence; the same three shapes are "
                    + "accepted on the same UTC assumption, except that a bare `2026-08-11` here "
                    + "means the END of that UTC day — so the same date in both bounds is that one "
                    + "whole day. This bound is also what decides an empty answer: a window whose "
                    + "end is already well past reports `not_transcribed` rather than sending you "
                    + "back to wait, even for a recurring series with occurrences still to come."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_TRANSCRIPTS,
                description=(
                    "How many transcripts to return. Default 20, maximum "
                    + f"{MAX_TRANSCRIPTS}. They are the NEWEST that many of the "
                    + "window, not the first that many Microsoft happens to answer with: the "
                    + f"meeting's transcripts are read (up to {MAX_ARTIFACT_SCAN} of "
                    + "them, which is this call's whole cost) and ordered before this cuts them, "
                    + "so asking for 3 gives the 3 newest OF THE ONES READ. Those are the 3 latest "
                    + "outright whenever the meeting has no more transcripts than that cap, which "
                    + "is every meeting except a series recorded daily for most of a year: one "
                    + "meeting has one transcript per occurrence that was transcribed. Past the "
                    + "cap the read stops mid-collection, in whatever order Microsoft answered in "
                    + "(it offers no way to ask for the newest), so a newer transcript can be one "
                    + "that was never read — `include_scan_completeness` is how to find out, and "
                    + "raising `limit` does not read further. Getting `limit` transcripts back "
                    + "means the window may hold older ones; getting fewer means it does not."
                ),
            ),
        ] = 20,
        include_scan_completeness: Annotated[
            bool,
            Field(
                description=(
                    "Report whether the read reached the end of this meeting's transcripts, as "
                    + "`scan_incomplete` in the answer. Off by default, and worth setting for one "
                    + "question: whether the first transcript listed is the meeting's own latest. "
                    + "It is, for every meeting with no more transcripts than one call reads "
                    + f"({MAX_ARTIFACT_SCAN}) — which is every meeting bar a series "
                    + "recorded daily for most of a year — and past that the order is over the "
                    + "ones read. You do not need it to trust an empty answer: `status` already "
                    + "reports `scan_incomplete` when nothing was found and the read stopped short."
                )
            ),
        ] = False,
        graph_token: str = _TOKEN,
    ) -> MeetingTranscripts:
        handle = meeting_handle(meeting_uri)
        if handle is None:
            raise ToolError(_NOT_A_MEETING_HANDLE)
        with graph_tool_errors(*GRAPH_PERMISSIONS):
            return await list_meeting_transcripts(
                graph_client_for(transport, graph_token),
                handle=handle,
                started_after=started_after,
                started_before=started_before,
                limit=limit,
                include_scan_completeness=include_scan_completeness,
            )
