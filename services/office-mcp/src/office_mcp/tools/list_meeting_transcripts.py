"""`list_meeting_transcripts` — transcripts a Teams meeting holds, and whether it was transcribed.

First half of reading: this says what exists; `read_transcript` returns what was said. Two tools
because transcripts are large and recurring meetings are one meeting to Graph — occurrences share
one collection, distinguished only by transcription start time.

Meeting address, join-URL escaping, occurrence window, and "newest first" promises are in
`shared/meetings.py` — they are meeting facts, shared with a second artifact reader if one came.
Transcript handle grammar is in `shared/handles.py` — the handle this tool mints is what
`read_transcript` parses.

Five answers, five actions: GraphAccessToTranscriptsDisabled (off by default, admin-only fix) /
available (newest first over those read) / not_transcribed (never recorded or transcribed, no
retry) / not_ready (window just closed; retry permitted; Graph publishes no SLA) /
scan_incomplete (more transcripts than one call reads; none match window; stop).

Newest first: Graph has no orderby on transcripts. Read up to MAX_ARTIFACT_SCAN, sort, cut to
limit. For meetings under the cap, first entry is latest. A walk stopped at limit before sorting
would return wrong answer with right shape. This is what makes newest_in_window a named function.

`GET …/transcripts` returning nothing is not one answer but three, and the tenant switch is a
fourth:

* **`GraphAccessToTranscriptsDisabled`** — a `403` whose remedy names a Teams administrator, not a
  Graph permission. Microsoft Graph access to meeting transcripts is off by default and "no app can
  access meeting transcripts, regardless of app-level permissions"; there is "no request-side
  workaround", so re-consent is explicitly ruled out. It is recognised by inner code in
  `shared/seam.py`, where every other refusal is worded. Microsoft scopes the switch to transcript
  resources, so it does **not** cover recordings, which is why `list_meeting_recordings` is a second
  tool rather than a second field here: in a tenant that has never touched the switch, this call
  fails and that one answers.
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
the shape of a right one. `newest_in_window` is where that happens, for both listers.

`include_scan_completeness` is opt-in because it is the only thing here a caller cannot work out for
itself. "The window held more transcripts than your `limit`" it can: a full window may have more
behind it, which is what a page size means everywhere. "The read stopped at the cap" it cannot, and
merging the two into one flag would give one name to two facts with opposite remedies — raise
`limit` for the first, nothing at all for the second. A *short* window is where the two touch, and
the descriptions are worded for it: fewer than `limit` means the window holds no more than was
read, which is the whole window only while the read reached the end of the collection. Where nothing
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

from office_mcp.graph_client import graph_errors
from office_mcp.shared.handles import MeetingHandle, TranscriptHandle, meeting_handle
from office_mcp.shared.meetings import (
    MAX_ARTIFACT_SCAN,
    MEETING_PERMISSION,
    TRANSCRIPT_PERMISSION,
    OccurrenceWindow,
    newest_in_window,
    resolve_meeting,
)
from office_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "list_meeting_transcripts"

# Two permissions: resolve and read. Both under one token; Entra redeems together or not at all.
# read_transcript declares the second alone (handles the resolved id). Transcript permission shared
# with read_transcript; named in shared/meetings.py (rule 4 keeps tool files apart).
GRAPH_PERMISSIONS: tuple[str, ...] = (MEETING_PERMISSION, TRANSCRIPT_PERMISSION)

# Maximum transcripts to return. Graph documents `$top` but publishes no ceiling, so this is ours.
MAX_TRANSCRIPTS = 50

_DESCRIPTION = f"""\
List transcripts a Teams meeting has, if any. Takes the `meeting_uri` from list_chats.

First half of reading: this lists what exists; read_transcript returns the words. Two calls because
transcripts are large and recurring meetings are one collection to Microsoft.

**Read `status` before anything else. Five values, five actions:**
- `available` — transcripts are listed, newest first. Use read_transcript.
- `not_ready` — nothing is there yet for the window you asked about and something might still
arrive. Wait and call again later. This is NOT "there is no transcript". Microsoft publishes no
availability SLA; this tool infers timing from the window (or meeting) end and errs towards "wait".
An occurrence window that is already well past never answers this.
- `not_transcribed` — the window is over, nothing is there, nothing is expected.
Retrying will not help. Say the meeting has no transcript, not that the meeting did not happen.
- `scan_incomplete` — this meeting holds more than {MAX_ARTIFACT_SCAN} transcripts and none read
fall in your window, so whether one exists there is not known. Window applies after Microsoft
answers, not in the request, so narrower `started_after`/`started_before`
reads the same transcripts and returns this same answer. Stop here. There is nothing to try.
Never report it as "there is no transcript" — that is not what this status means.
- `meeting_not_found` — Microsoft matched the join URL to no meeting this user can see.

For recurring meetings, scope to one occurrence with `started_after`/`started_before`; a one-off
meeting has a single transcript and needs neither. Both bounds take a date (that whole UTC day) or
a timestamp, with or without offset — no offset reads as UTC.

This tool answers transcripts only. Recording exists is a separate question (different permission),
so transcript refusal says nothing about whether a recording exists. Transcript reading is an org-
wide Teams setting, OFF by default. When off, the error names the admin who can turn it on.
Participants may be refused where the organiser succeeds. The two permissions are independent.
"""

# Error: wrong tool called with wrong handle shape. Prevent confusion with read_transcript handles.
_NOT_A_MEETING_HANDLE = (
    "list_meeting_transcripts takes teams:///meetings/{join_web_url} from list_chats, not this "
    + "shape. Call list_chats and use its `meeting_uri`. A `teams:///transcripts/...` handle is "
    + "not a meeting handle — that last one is read_transcript's, and this tool is what produces "
    + "it. Retrying this value will fail identically."
)


class TranscriptSummary(BaseModel):
    uri: str = Field(
        description=(
            "Handle for this transcript. Pass to read_transcript to get the words. Nothing here "
            "contains them."
        )
    )
    transcript_id: str = Field(
        description="Transcript Graph id. Use `uri` to identify a transcript, not this alone."
    )
    started_at: datetime | None = Field(
        description=(
            "Transcription start. For recurring meetings, distinguishes one occurrence from "
            "another."
        )
    )
    ended_at: datetime | None = Field(description="Transcription end.")
    content_correlation_id: str | None = Field(
        description=(
            "Microsoft's id linking this transcript to the recording of the same call. Two "
            "transcripts with the same id are two views of one call."
        )
    )


class MeetingTranscripts(BaseModel):
    status: str = Field(
        description=(
            "What was found, and what to do next. One of:\n"
            + "- `available` — transcripts are listed, newest first.\n"
            + "- `not_ready` — nothing is there yet and something may still arrive. A window that "
            + "has demonstrably passed is never reported this way, however far in the future a "
            + "recurring series runs. This is inferred; Microsoft publishes no availability SLA.\n"
            + "- `not_transcribed` — the window is over, nothing is there, nothing expected. "
            + "Retrying will not change this.\n"
            + "- `scan_incomplete` — this meeting has more transcripts than one call reads "
            + f"({MAX_ARTIFACT_SCAN}) and none read fall in your window, so whether one exists "
            + "there is NOT known. There is nothing to try. Changing `started_after`/"
            + "`started_before` reads the same transcripts and returns this same status. This "
            + "status is final and cannot be retried or worked around by narrowing the window. "
            + "Never report this as 'there is no transcript'.\n"
            + "- `meeting_not_found` — Microsoft matched the join URL to no meeting this user can "
            + "see. Do not retry and do not rebuild the handle."
        )
    )
    meeting_id: str | None = Field(
        description=(
            "Resolved meeting's Graph id, or null if `status` is `meeting_not_found`. Transcript "
            "`uri` carries this."
        )
    )
    subject: str | None = Field(
        description="Meeting subject as Microsoft holds it. Confirm this is the right meeting."
    )
    meeting_type: str | None = Field(
        description=(
            "`scheduled`, `recurring`, `adhoc`, `meetNow`, `broadcast`, or null. When `recurring`, "
            "use `started_after`/`started_before` to reach one occurrence."
        )
    )
    started_at: datetime | None = Field(
        description="Meeting start. For recurring series, Microsoft's value for the whole series."
    )
    ended_at: datetime | None = Field(description="Meeting end (same caveat as `started_at`).")
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
            + f"{MAX_TRANSCRIPTS}. Fewer than `limit` means these are the whole window OF WHAT "
            + "WAS READ, which is the whole window itself for any meeting inside that cap and for "
            + "no meeting past it: a transcript of your window can be one that was never read, and "
            + "a short list cannot tell you which case you are in — `include_scan_completeness` "
            + "can. There is no cursor. Empty for every status other than `available`."
        )
    )
    scan_incomplete: bool | None = Field(
        description=(
            f"Whether read stopped at {MAX_ARTIFACT_SCAN} transcripts (true), read all (false), "
            "or null if not requested. Set only when `include_scan_completeness` is true. True "
            "means transcripts ordered over those read, not the meeting. False means order and "
            "absence are exact."
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
    """Transcripts of the meeting and what to do about them.

    At most two Graph requests: resolve URL, then list. Window is applied after fetching.
    """
    assert 1 <= limit <= MAX_TRANSCRIPTS, f"limit must be within 1..{MAX_TRANSCRIPTS}, got {limit}"
    window = OccurrenceWindow.of(started_after, started_before)

    with graph_errors(TOOL_NAME):
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
    """Which empty answer to give.

    Hit cap? scan_incomplete. Window settled? not_transcribed. Otherwise not_ready.
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
    """Register this tool against the shared Graph transport."""
    # Built here because this is where `transport` is, and named rather than called in the default.
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

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
                    "The meeting from list_chats: teams:///meetings/{join_web_url}. Copy "
                    "verbatim. Microsoft matches character for character."
                ),
            ),
        ],
        started_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Scope to one occurrence by filtering transcripts start time. Shapes: "
                    "2026-08-11T09:00:00+02:00 (with offset) or 2026-08-11T09:00:00 (IS READ AS "
                    "UTC) or 2026-08-11 (whole UTC day, first instant). Pass offset for local "
                    "time — 09:00 in Zurich is 07:00Z."
                )
            ),
        ] = None,
        started_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Upper bound for transcription start. Pair with `started_after`. A bare "
                    "`2026-08-11` means the END of that UTC day — same date in both bounds is "
                    "that whole day."
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
                    + "means the window may hold older ones; getting fewer means the window holds "
                    + "no more THAN WAS READ, which is the whole window except past that cap."
                ),
            ),
        ] = 20,
        include_scan_completeness: Annotated[
            bool,
            Field(
                description=(
                    "Report `scan_incomplete`: did read reach the end (may be limited to "
                    f"{MAX_ARTIFACT_SCAN})? Off by default. `status` already reports "
                    "`scan_incomplete` when nothing was found and read stopped short."
                )
            ),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> MeetingTranscripts:
        handle = meeting_handle(meeting_uri)
        if handle is None:
            raise ToolError(_NOT_A_MEETING_HANDLE)
        return await list_meeting_transcripts(
            client,
            handle=handle,
            started_after=started_after,
            started_before=started_before,
            limit=limit,
            include_scan_completeness=include_scan_completeness,
        )
