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

include_scan_completeness is opt-in: it reports one thing the caller cannot see: did the read
reach the end? Full limit means older ones may exist; fewer than limit means this is the whole
window. The "read hit the cap" fact must be explicit.
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
            "Transcripts in the window, newest first. Ordered over those read (up to "
            f"{MAX_ARTIFACT_SCAN}), not a Microsoft page. Full `limit` means older may exist; "
            "fewer than `limit` means this is the whole window. Empty except when status is "
            "`available`."
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
                    f"Max to return (default 20, max {MAX_TRANSCRIPTS}). Newest of window. Read "
                    f"(up to {MAX_ARTIFACT_SCAN}) and sorted before cutting. Full list means "
                    "older may exist; fewer means none beyond."
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
