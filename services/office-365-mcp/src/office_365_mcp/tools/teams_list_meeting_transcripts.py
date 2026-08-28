"""`teams_list_meeting_transcripts` — transcripts a Teams meeting holds and whether it was
transcribed.

TRAP: transcript access is a tenant-wide Teams switch, OFF by default, and every call answers 403
while it is off. It is not a permission; it needs admin action. Microsoft scopes the switch to
transcripts, so in an untouched tenant this fails and `teams_list_meeting_recordings` answers.

TRAP: Graph can return an empty page that still carries a next link, so an empty page is not the
end of the collection. `graph_client/pagination.py` follows the link; without that, a meeting Graph
pages as `[3, nothing, 1]` would look like it held only 3 transcripts.

Newest first: Graph has no `$orderby`. Read up to MAX_ARTIFACT_SCAN, sort, then cut to `limit` —
cutting first returns an arbitrary subset sorted among itself, a wrong answer in the right shape.
That is why `newest_in_window` is a named function.

The window applies after fetching. Graph documents no filterable date on this collection, only
`contentCorrelationId` (https://learn.microsoft.com/en-us/graph/api/calltranscript-get, Example 11),
so any window reads the same MAX_ARTIFACT_SCAN artifacts and narrowing returns the same answer.
"""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Annotated, Literal, Self

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.call_transcript import CallTranscript
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared.handles import MeetingHandle, TranscriptHandle, meeting_handle
from office_365_mcp.shared.meetings import (
    MAX_ARTIFACT_SCAN,
    MEETING_PERMISSION,
    TRANSCRIPT_PERMISSION,
    OccurrenceWindow,
    newest_in_window,
    resolve_meeting,
)
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_list_meeting_transcripts"

# The meeting resolve before this one counts under `shared/meetings.py`'s own step, not this.
STEP_TRANSCRIPTS = "transcripts"

# Meeting resolve and transcript read, redeemed under one token by Entra. The transcript permission
# lives in `shared/meetings.py`: `tests/test_layering.py` rule 4 forbids importing
# teams_read_transcript.
GRAPH_PERMISSIONS: tuple[str, ...] = (MEETING_PERMISSION, TRANSCRIPT_PERMISSION)

# Invented ids, but a shape this tool accepts: an argument it rejects never reaches Graph.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "meeting_uri": "teams:///meetings/https%3A%2F%2Fteams.microsoft.invalid%2Fl%2Fmeetup-join"
    + "%2F19%253ameeting_TjAwMDAwMDAwMDAwMA%2540thread.v2%2F0"
}

# Max transcripts per call. Graph documents `$top` but publishes no ceiling, so this limit is ours.
MAX_TRANSCRIPTS = 50

# This connector's own vocabulary, not Microsoft's, so it is closed and publishes as an enum
# in the output schema rather than as a bare string a model has to mine out of the prose.
# Graph-owned vocabularies (`meeting_type` here) stay `str`, because Microsoft may add a
# member at any time. Bare assignment, not `type X = ...`: PEP 695 aliases publish as a
# `$ref` into `$defs`, which puts the values one hop away from the property a model reads.
TranscriptStatus = Literal[
    "available", "not_ready", "not_transcribed", "scan_incomplete", "meeting_not_found"
]

_DESCRIPTION = """\
List a Teams meeting's transcripts, from the `meeting_uri` teams_list_chats reports. Call it to \
learn whether a meeting was transcribed; teams_read_transcript returns the words. Read `status` \
first: `not_ready` means wait, `not_transcribed` means none, `scan_incomplete` means unknowable — \
stop, narrowing the window changes nothing. A tenant switch can block transcripts and never \
recordings, so try teams_list_meeting_recordings on refusal. Returns `status` and each \
transcript's `uri` and times. \
"""

_NOT_A_MEETING_HANDLE = (
    "teams_list_meeting_transcripts takes teams:///meetings/{join_web_url} from teams_list_chats, "
    + "not this. "
    + "Call teams_list_chats and use its `meeting_uri`. A `teams:///transcripts/...` handle is "
    + "teams_read_transcript's; this tool is what produces it. Retrying this value will fail "
    + "identically."
)


class TranscriptSummary(BaseModel):
    uri: str = Field(
        description="Handle for this transcript. Pass to teams_read_transcript to get the words."
    )
    transcript_id: str = Field(
        description="Transcript Graph id. Use `uri` to identify a transcript, not this alone."
    )
    started_at: datetime | None = Field(
        description=(
            "Transcription start. For recurring meetings, distinguishes one occurrence from "
            + "another."
        )
    )
    ended_at: datetime | None = Field(description="Transcription end.")
    content_correlation_id: str | None = Field(
        description="Microsoft's id linking this transcript to the recording of the same call."
    )

    @classmethod
    def from_transcript(cls, meeting_id: str, transcript: CallTranscript) -> Self:
        assert transcript.id is not None, "Graph returned a transcript with no id"
        return cls(
            uri=TranscriptHandle(meeting_id, transcript.id).uri,
            transcript_id=transcript.id,
            started_at=transcript.created_date_time,
            ended_at=transcript.end_date_time,
            content_correlation_id=transcript.content_correlation_id,
        )


class MeetingTranscripts(BaseModel):
    status: TranscriptStatus = Field(
        description=(
            "What was found and what to do next. One of:\n"
            + "- `available` — transcripts are listed, newest first.\n"
            + "- `not_ready` — nothing is there yet and something may still arrive. Wait and call "
            + "again later. This is NOT 'there is no transcript'. A window that has demonstrably "
            + "passed is never reported this way, however far in the future a recurring series "
            + "runs. This is inferred; Microsoft publishes no availability SLA.\n"
            + "- `scan_incomplete` — this meeting has more transcripts than one call reads "
            + f"({MAX_ARTIFACT_SCAN}) and none read fall in your window, so whether one exists "
            + "there "
            + "is NOT known. There is nothing to try. Stop here. This status is final and cannot "
            + "be "
            + "retried or worked around by narrowing the window. Never report this as 'there is no "
            + "transcript'.\n"
            + "- `not_transcribed` — the window is over; nothing is there; nothing expected. "
            + "Retrying will not change this.\n"
            + "- `meeting_not_found` — Microsoft matched the join URL to no meeting this user can "
            + "see. Do not retry and do not rebuild the handle.\n"
            + "A refusal is about this user, not about the meeting: a participant may be refused "
            + "where the organiser succeeds."
        )
    )
    meeting_id: str | None = Field(
        description="Resolved meeting's Graph id, or null if `status` is `meeting_not_found`."
    )
    subject: str | None = Field(
        description="Meeting subject as Microsoft holds it. Confirms this is the right meeting."
    )
    meeting_type: str | None = Field(
        description=(
            "`scheduled`, `recurring`, `adhoc`, `meetNow`, `broadcast`, or null. When `recurring`, "
            + "use `started_after`/`started_before` to reach one occurrence."
        )
    )
    started_at: datetime | None = Field(
        description=(
            "Meeting start. For recurring series, Microsoft's single value for the whole series."
        )
    )
    ended_at: datetime | None = Field(description="Meeting end (same caveat as `started_at`).")
    transcripts: list[TranscriptSummary] = Field(
        description=(
            "Transcripts that fall inside the requested window, newest first. The order is over "
            + f"every transcript this call read (up to {MAX_ARTIFACT_SCAN}), not over one page of "
            + "Microsoft's answer. For meetings with fewer transcripts than that cap — all but "
            + "series recorded daily for most of a year — the first entry is the latest of the "
            + "window. Past the cap the first entry is the latest of what was READ; Microsoft "
            + "returns this collection in its own order and offers no `$orderby`. Set "
            + "`include_scan_completeness` to learn if the read reached the end. As many as "
            + "`limit` "
            + "means the window may hold older ones; fewer means the window holds no more than was "
            + "read. Empty for every status other than `available`."
        )
    )
    scan_incomplete: bool | None = Field(
        description=(
            f"Whether read stopped at {MAX_ARTIFACT_SCAN} transcripts (true), read all (false), or "
            + "null if not requested. Set only when `include_scan_completeness` is true. True "
            + "means "
            + "transcripts ordered over those read, not all. False means order and absence are "
            + "exact."
        )
    )


async def teams_list_meeting_transcripts(
    client: GraphServiceClient,
    *,
    handle: MeetingHandle,
    started_after: date | datetime | None,
    started_before: date | datetime | None,
    limit: int,
    include_scan_completeness: bool,
) -> MeetingTranscripts:
    """Transcripts of the meeting `handle` addresses. At most two Graph requests: resolve, list."""
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
        with graph_step(STEP_TRANSCRIPTS):
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
        # meetingType is a generated enum. Unknown values deserialize to None, not to an error.
        meeting_type=meeting.meeting_type,
        started_at=meeting.start_date_time,
        ended_at=meeting.end_date_time,
        transcripts=[
            TranscriptSummary.from_transcript(meeting.id, transcript) for transcript in found
        ],
        scan_incomplete=collected.capped if include_scan_completeness else None,
    )


def _absence(*, scan_stopped_short: bool, settled: bool) -> TranscriptStatus:
    """Which empty answer: cap hit, window settled, or neither."""
    if scan_stopped_short:
        return "scan_incomplete"
    return "not_transcribed" if settled else "not_ready"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    # Closes over `transport` here; the default below holds this name, not a call (ruff's B008).
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
                    "Meeting handle from teams_list_chats: teams:///meetings/{join_web_url}. Copy "
                    + "verbatim."
                ),
            ),
        ],
        started_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Scope to one occurrence by filtering transcription start time. Shapes: "
                    + "2026-08-11T09:00:00+02:00 (with offset), 2026-08-11T09:00:00 (IS READ AS "
                    + "UTC), or 2026-08-11 (whole UTC day, first instant). Pass offset for local "
                    + "time — 09:00 in Zurich is 07:00Z."
                )
            ),
        ] = None,
        started_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Upper bound for transcription start. Pair with `started_after`. A bare "
                    + "`2026-08-11` means the END of that UTC day."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_TRANSCRIPTS,
                description=(
                    f"How many transcripts to return. Default 20, maximum {MAX_TRANSCRIPTS}. These "
                    + "are the NEWEST that many of the window. All transcripts are read (up to "
                    + f"{MAX_ARTIFACT_SCAN}, the call's whole cost) and ordered before this cuts "
                    + "them. Past that cap they are the newest OF THE ONES READ, not the meeting's "
                    + "newest."
                ),
            ),
        ] = 20,
        include_scan_completeness: Annotated[
            bool,
            Field(
                description=(
                    "Report whether read reached the end of transcripts, as `scan_incomplete`. Off "
                    + "by default."
                )
            ),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> MeetingTranscripts:
        handle = meeting_handle(meeting_uri)
        if handle is None:
            raise ToolError(_NOT_A_MEETING_HANDLE)
        return await teams_list_meeting_transcripts(
            client,
            handle=handle,
            started_after=started_after,
            started_before=started_before,
            limit=limit,
            include_scan_completeness=include_scan_completeness,
        )
