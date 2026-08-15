"""`list_meeting_transcripts` — whether a Teams meeting was transcribed, and a handle for each.

This is the first half of reading a meeting. It says what exists; `read_transcript` returns what was
said. Two tools rather than one because a transcript is large and because a recurring series is a
single meeting to Graph — every occurrence's transcript lands in the same collection, distinguished
only by when transcription started — so which one to read is a decision rather than a default.

How a meeting is addressed, how the join URL is escaped onto the wire, what an occurrence window is,
and how far "newest first" is true are all `shared/meetings.py`: they are promises about the meeting
rather than about its transcripts, and this file is only the first tool to need them. The handle
grammar itself is `shared/handles.py`, for the same reason one step further out: the transcript
handle this file mints is the one `read_transcript` parses, and a second speller would look like a
handle one tool produced and another answers 404 to.

## Five answers that need different action

`GET …/transcripts` returning nothing means exactly one of five things:

* **`GraphAccessToTranscriptsDisabled`** — a `403` with no fix on this server. Microsoft Graph
  access to transcripts is off by default across the tenant and requires a Teams administrator to
  turn on. Re-consent does not help. Detected by code in `shared/seam.py`. Microsoft scopes this
  switch to transcripts only, not recordings, so a refusal here says nothing about whether the
  meeting was recorded.
* **`available`** — transcripts exist and are listed, newest first (of the ones read up to
  `MAX_ARTIFACT_SCAN`).
* **`not_transcribed`** — the meeting was never recorded or never transcribed. Retrying does not
  help.
* **`not_ready`** — the window just closed or the meeting just ended. Retrying is the only option.
  Graph publishes no SLA for availability, so this is an inference: if the window is still fresh
  (within ~5–60 days of the meeting, depending on tenant policy), the lack of a transcript may mean
  transcription is still in progress. A window that is demonstrably old (the meeting ended more than
  60 days ago, or a one-time meeting has passed its 60-day expiration) never gives this answer.
  Do not report this status as "there is no transcript" — it means "not ready yet".
* **`scan_incomplete`** — the meeting holds more than `MAX_ARTIFACT_SCAN` transcripts and none of
  the ones read fall in your window, so whether one exists there is not known. The window is applied
  *after* Microsoft answers, not in the request, so a narrower window reads the same transcripts and
  returns this same answer. Stop here. There is nothing to try.

## Newest first is bounded by what was read

Graph documents no `$orderby` on transcripts, so it answers in its own order. The code reads up to
`MAX_ARTIFACT_SCAN` transcripts, sorts them, and cuts to `limit`. For meetings with no more
transcripts than that cap (every meeting except a series recorded daily for most of a year), the
first entry is the latest. A walk that stopped at `limit` before sorting would return wrong answer
with right shape.

`include_scan_completeness` is opt-in because it tells one thing a caller cannot infer: whether the
read reached the end of the meeting's transcripts. A full `limit` means the window may hold older
ones. Fewer than `limit` means these are the whole window. But "the read stopped at the cap" must be
explicit.
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
# resolve that precedes it: a tenant can grant one and withhold the other. `read_transcript` names
# this same one, because it reads the same resource — two tools declaring one permission is what the
# registry's deduplication is for, and neither may leave it out. The name comes from
# `shared/meetings.py` for that reason: rule 4 forbids the two tools sharing a constant of their
# own, so a permission each of them declares is spelled where neither owns it.
#
# What listing a meeting's transcripts costs: the resolve and the list, in that order, under one
# token — Entra redeems them together or not at all. Reading content needs only the second, since
# the handle minted below already carries the resolved meeting id, which is why `read_transcript`
# declares that one alone and can still answer in a tenant that withholds `OnlineMeetings.Read`.
GRAPH_PERMISSIONS: tuple[str, ...] = (MEETING_PERMISSION, TRANSCRIPT_PERMISSION)

# Built at import: a call inside a parameter default rebuilds it on every registration.
_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

# Maximum transcripts to return. Graph documents `$top` but publishes no ceiling, so this is ours.
MAX_TRANSCRIPTS = 50

_DESCRIPTION = f"""\
Find whether a Teams meeting was transcribed, and get a handle for each transcript. Takes the \
`meeting_uri` that list_chats reports on a meeting chat.

This is the first half of reading a meeting: this tool says what exists, read_transcript returns \
what was said. Two calls rather than one because a transcript is large and because a recurring \
meeting is a single meeting to Microsoft — every occurrence's transcript lands in the same \
collection, distinguished only by when transcription started — so which one to read is a decision, \
not a default. Scope to one occurrence with `started_after`/`started_before` when \
`meeting_type` comes back `recurring`; a one-off meeting has a single transcript and needs \
neither. Both bounds take a date (`2026-08-11`, meaning that whole UTC day) or a timestamp, with \
or without a timezone offset — one without is read as UTC, so pass the offset when you are working \
from a local time.

**Read `status` before anything else. It has five values and they mean five different actions:**
- `available` — transcripts are listed, newest first; read one with read_transcript. "Newest" is \
over the transcripts this call read, which is every transcript the meeting has unless the meeting \
holds more of them than the cap below — set `include_scan_completeness` if the answer turns on that.
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
({MAX_ARTIFACT_SCAN}) and none of the ones read fall in your window, so whether one \
exists there is not known. The window is applied after Microsoft has answered, not in the request, \
so a narrower `started_after`/`started_before` reads the same transcripts and returns this same \
answer. Stop here. There is nothing to try. Never report it as "there is no transcript".
- `meeting_not_found` — Microsoft matched the join URL to no meeting this user can see. Do not \
retry and do not rebuild the handle.

This tool answers about transcripts only. Whether the meeting was recorded is a separate question \
that Microsoft gates independently via a different permission (`OnlineMeetingRecording.Read.All`), \
so a refusal on transcripts says nothing about whether a recording exists or is accessible. \
No video is returned; a transcript is better for questions about a meeting.

Reading transcripts over Microsoft Graph is an organisation-wide Teams setting, OFF by default. \
When off, the error names the administrator who can turn it on. Separately, Microsoft documents \
transcript access under {TRANSCRIPT_PERMISSION} without stating participants get it, so a \
participant may be refused where the organiser would succeed. The two meeting permissions \
(`OnlineMeetings.Read` and `OnlineMeetingTranscript.Read.All`) are independent scopes granted \
separately: a tenant can grant one and withhold the other.\
"""

# Error message for invalid meeting_uri. Unique to this tool to prevent a caller being sent to
# the wrong tool.
_NOT_A_MEETING_HANDLE = (
    "list_meeting_transcripts takes the `meeting_uri` that list_chats reports on a meeting chat, "
    + "and this is not one. A meeting handle has exactly one shape:\n"
    + "  teams:///meetings/{join_web_url}\n"
    + "with the join URL percent-encoded. It cannot be assembled — Microsoft addresses a "
    + "meeting by the join URL of the Teams meeting itself, which only Microsoft can supply — "
    + "so call list_chats, find the `meeting` chat for the meeting in question, and pass its "
    + "`meeting_uri` verbatim. A chat id, a chat topic, a Teams web link and a "
    + "`teams:///transcripts/...` handle are none of them a meeting handle — that last one is "
    + "read_transcript's, and this tool is what produces it. Retrying this value will fail "
    + "identically."
)


class TranscriptSummary(BaseModel):
    uri: str = Field(
        description=(
            "A handle for this transcript. Pass it verbatim to read_transcript, which is the only "
            + "route to the words that were said — nothing here contains any of them."
        )
    )
    transcript_id: str = Field(
        description="The transcript's Graph id. Use `uri` to identify a transcript, not this alone."
    )
    started_at: datetime | None = Field(
        description=(
            "When transcription began. For a recurring meeting this tells one occurrence from "
            + "another: all occurrences share one collection, and Microsoft gives no occurrence id."
        )
    )
    ended_at: datetime | None = Field(description="When transcription ended.")
    content_correlation_id: str | None = Field(
        description=(
            "Microsoft's identifier linking this transcript to the recording of the same call. "
            + "Two transcripts sharing this value are two views of one call, not two separate "
            + "calls. Presence of this id does not guarantee a recording exists; use this only to "
            + "correlate transcript and recording if you already have both."
        )
    )


class MeetingTranscripts(BaseModel):
    status: str = Field(
        description=(
            "What was found, and what to do next. One of:\n"
            + "- `available` — `transcripts` lists them, newest first.\n"
            + "- `not_ready` — nothing is there yet and something may still arrive. Microsoft "
            + "publishes no availability SLA, so this is inferred. A window that has demonstrably "
            + "passed is never reported this way, however far in the future a recurring series "
            + "runs.\n"
            + "- `not_transcribed` — the window is over, nothing is there, nothing is expected. "
            + "Retrying will not change this.\n"
            + "- `scan_incomplete` — this meeting has more transcripts than one call reads "
            + f"({MAX_ARTIFACT_SCAN}) and none of the ones read fall in your window, so whether "
            + "one exists there is NOT known. There is nothing to try: changing "
            + "`started_after`/`started_before` reads the same transcripts and returns this same "
            + "status. Stop and report that the collection is too large to scan completely and "
            + "whether a transcript exists in that window cannot be determined. This status is "
            + "final and cannot be retried or worked around by narrowing the window. Never report "
            + "this as 'there is no transcript'.\n"
            + "- `meeting_not_found` — Microsoft matched the join URL to no meeting this user can "
            + "see. Do not retry and do not rebuild the handle."
        )
    )
    meeting_id: str | None = Field(
        description=(
            "The resolved meeting's Graph id, or null when `status` is `meeting_not_found`. "
            + "A transcript's `uri` carries this already. This id is opaque; "
            + "no MCP tool here builds or interprets it."
        )
    )
    subject: str | None = Field(
        description=(
            "The meeting's subject as Microsoft holds it. Confirm this is the meeting you meant."
        )
    )
    meeting_type: str | None = Field(
        description=(
            "`scheduled`, `recurring`, `adhoc`, `meetNow`, `broadcast`, or null. When `recurring`, "
            + "every occurrence's transcript is in one collection. Use "
            + "`started_after`/`started_before` to reach a single occurrence."
        )
    )
    started_at: datetime | None = Field(
        description=(
            "When the meeting starts. For a recurring series this is Microsoft's value for the "
            + "whole series, not the occurrence you asked about."
        )
    )
    ended_at: datetime | None = Field(
        description="When the meeting ends (same caveat as `started_at`)."
    )
    transcripts: list[TranscriptSummary] = Field(
        description=(
            "Transcripts in the requested window, newest first. Ordered over every transcript "
            + f"read (up to {MAX_ARTIFACT_SCAN}), not over one page of Microsoft's answer. For "
            + f"meetings with no more transcripts than {MAX_ARTIFACT_SCAN}, these are all of "
            + "them. A full `limit` means the window may hold older ones — raise `limit` up to "
            + f"{MAX_TRANSCRIPTS}. Fewer than `limit` means these are the whole window. Empty "
            + "for every status other than `available`. No cursor available."
        )
    )
    scan_incomplete: bool | None = Field(
        description=(
            f"Whether the read stopped at {MAX_ARTIFACT_SCAN} transcripts (true), or read the "
            + "whole collection (false), or null when `include_scan_completeness` was not set. "
            + "Only set when `include_scan_completeness` is true. When true, `transcripts` is "
            + "ordered over the ones read, not the whole meeting. When false, the order and any "
            + "absence within the window are exact. Note: `status` reports `scan_incomplete` "
            + "when nothing was found and the read "
            + "stopped short, regardless of this field's value — this field only matters when "
            + "`status` is `available` and shows whether the result set is complete."
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
    """Transcripts of the meeting `handle` addresses, and what a caller should do about them.

    Makes at most two Graph requests: resolve the join URL, then list transcripts. Lists all
    transcripts without filtering (Graph documents no date filter on transcripts), then applies the
    window while paging. The window bounds are instants (naive ones read as UTC). The same window
    decides which transcripts are kept and what an empty answer means.

    `include_scan_completeness` only changes whether `scan_incomplete` is reported, not what is
    read.
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
    """Which empty answer to give.

    If the scan hit the cap, artifacts past it might hold the one asked for. Nothing about absence
    is known, so return `scan_incomplete` — never `not_transcribed`. If settled, the window is
    old enough that any transcript falling in it would have appeared; return `not_transcribed`.
    Otherwise return `not_ready` — the window is still fresh.
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
    """Declare this tool against the shared Graph transport."""

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
                    "The meeting to list, exactly as list_chats reported `meeting_uri`: "
                    + "`teams:///meetings/{join_web_url}`. Copy it verbatim. Microsoft matches "
                    + "the join URL character for character, and nothing else identifies a meeting."
                ),
            ),
        ],
        started_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Reach one occurrence of a recurring meeting by filtering transcripts. Three "
                    + "shapes accepted: `2026-08-11T09:00:00+02:00` is that instant; "
                    + "`2026-08-11T09:00:00` with no offset IS READ AS UTC; `2026-08-11` is that "
                    + "whole UTC day, starting at its first instant. Pass the offset when you "
                    + "know a local time — 09:00 in Zurich is 07:00Z. A window in the wrong zone "
                    + "answers about the wrong hours."
                )
            ),
        ] = None,
        started_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Upper bound for transcription start time. Pair with `started_after` to reach "
                    + "one occurrence. A bare `2026-08-11` means the END of that UTC day — so the "
                    + "same date in both bounds is that whole day."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_TRANSCRIPTS,
                description=(
                    f"Maximum to return (default 20, maximum {MAX_TRANSCRIPTS}). Results are the "
                    + f"newest of the window. Transcripts are read (up to {MAX_ARTIFACT_SCAN}, "
                    + "this call's cost) and sorted before cutting to limit. A full list means "
                    + "older transcripts may exist; fewer than limit means none exist beyond."
                ),
            ),
        ] = 20,
        include_scan_completeness: Annotated[
            bool,
            Field(
                description=(
                    "Report `scan_incomplete` in the answer: whether the read reached the end of "
                    + f"this meeting's transcripts (may be limited to {MAX_ARTIFACT_SCAN} total). "
                    + "Off by default. You do not need it to trust an empty answer: `status` "
                    + "already reports `scan_incomplete` when nothing was found and the read "
                    + "stopped short."
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
