"""`list_meeting_recordings` — did a call record, how long it ran, and who may get the file.

TRAP: no video is returned or reachable anywhere in this connector. A Teams meeting runs 30 hours
max (https://learn.microsoft.com/en-us/microsoftteams/limits-specifications-teams) and Graph serves
a recording as one MP4 byte stream. `recordingContentUrl` is never returned either: that link opens
only with this connector's own token, so passing it on leaks a credential or does nothing.
`tests/test_layering.py` rule 7 blocks every module from addressing one recording, this file too.

Separate from `list_meeting_transcripts` because Graph gates them independently, under
`OnlineMeetingRecording.Read.All` and `OnlineMeetingTranscript.Read.All`, and a default tenant has
the transcript gate shut. One tool would have to either fail a reachable recording or hold two
incompatible statuses. `content_correlation_id` links them.

Newest first: Graph has no `$orderby` on this collection. Read up to MAX_ARTIFACT_SCAN, sort, then
cut to `limit`; stopping at `limit` before sorting returns an arbitrary subset sorted among itself.
"""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Annotated, Literal, Self

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.call_recording import CallRecording
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import graph_errors, graph_step
from office_mcp.shared import identity
from office_mcp.shared.handles import MeetingHandle, meeting_handle
from office_mcp.shared.meetings import (
    MAX_ARTIFACT_SCAN,
    MEETING_PERMISSION,
    RECORDING_PERMISSION,
    OccurrenceWindow,
    as_utc,
    newest_in_window,
    resolve_meeting,
)
from office_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "list_meeting_recordings"

# The meeting resolve counts under `shared/meetings.py`'s step and the identity check under
# `shared/identity.py`'s, so this names only the listing request and the walk that continues it.
STEP_RECORDINGS = "recordings"

# Meeting resolve, recordings read, and the identity check the organiser-only rule needs. Entra
# redeems all three under one token or none. The names live in `shared/meetings.py`.
GRAPH_PERMISSIONS: tuple[str, ...] = (
    MEETING_PERMISSION,
    RECORDING_PERMISSION,
    identity.GRAPH_PERMISSION,
)

# Invented ids, but a shape this tool accepts: an argument it rejects never reaches Graph.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "meeting_uri": "teams:///meetings/https%3A%2F%2Fteams.microsoft.invalid%2Fl%2Fmeetup-join"
    + "%2F19%253ameeting_TjAwMDAwMDAwMDAwMA%2540thread.v2%2F0"
}

# Max recordings per call. Graph sets no ceiling on `$top`, so this limit is ours.
MAX_RECORDINGS = 50

# Both vocabularies are this connector's, not Microsoft's, so they are closed and publish as enums
# in the output schema rather than as bare strings a model has to mine out of the prose. Graph-owned
# vocabularies (`meeting_type` here) stay `str`, because Microsoft may add a member at any time.
# Bare assignment, not `type X = ...`: PEP 695 aliases publish as a `$ref` into `$defs`, which puts
# the values one hop away from the property a model reads.
RecordingStatus = Literal[
    "available", "not_ready", "not_recorded", "scan_incomplete", "meeting_not_found"
]
ContentAccess = Literal["you_are_the_organizer", "organizer_only", "unknown"]

_DESCRIPTION = """\
List a Teams meeting's recordings from the `meeting_uri` list_chats reports. Call it to learn \
whether a meeting was recorded, how long, and who may download it — no video is returned or \
reachable here; for the words, call list_meeting_transcripts. Read `status` first: `not_ready` \
means wait, not "the call was not recorded". An `organizer_only` recording exists but is out of \
reach: never report it as missing. Returns `status` and each recording's times, duration and \
access.\
"""

# Local, not shared with list_meeting_transcripts: `tests/test_layering.py` rule 4 forbids that.
_NOT_A_MEETING_HANDLE = (
    "list_meeting_recordings takes the `meeting_uri` from list_chats: "
    "teams:///meetings/{join_web_url}. This is not one. Call list_chats, find the meeting chat, "
    "and pass its `meeting_uri` verbatim. A `teams:///transcripts/...` handle belongs to "
    "read_transcript. No recording is addressable here. Retrying this value will fail identically."
)


class RecordingSummary(BaseModel):
    recording_id: str = Field(
        description=(
            "Recording's Graph id. Opaque; no tool here uses it. This connector has no recording "
            "handle."
        )
    )
    started_at: datetime | None = Field(
        description=(
            "When recording began (Microsoft's `createdDateTime`), not the meeting's. For "
            "recurring meetings, this distinguishes one occurrence from another."
        )
    )
    ended_at: datetime | None = Field(
        description="When recording stopped (Microsoft's `endDateTime`)."
    )
    duration_seconds: float | None = Field(
        description=(
            "Recording length: `ended_at - started_at`. Microsoft publishes no duration field, so "
            "this is derived and null if either timestamp is missing. It is the recording's "
            "length, not the meeting's."
        )
    )
    content_access: ContentAccess = Field(
        description=(
            "Whether the SIGNED-IN user may download this recording. Not about this connector "
            "(which has no video). One of:\n"
            "- `you_are_the_organizer` — user is the organiser; Microsoft permits download in "
            "Teams or SharePoint, not here. Admin can still block tenant-wide.\n"
            "- `organizer_only` — user is not the organiser. Microsoft: 'Meeting participants "
            "don't have permission to download meeting recordings' unless admin unblocks them. "
            "This is NOT a missing recording: it exists; the video is out of reach.\n"
            "- `unknown` — Microsoft named no organiser, so cannot tell which above applies."
        )
    )
    organizer_user_id: str | None = Field(
        description=(
            "Organiser's Entra object id, or null. The person to ask when `content_access` is "
            "`organizer_only`. Microsoft leaves the organiser's display name null on this "
            "resource, so this id is all there is. Comparable with get_me's `user_id` and message "
            "sender `user_id`."
        )
    )
    content_correlation_id: str | None = Field(
        description=(
            "Microsoft's identifier linking this recording to its transcript. Call "
            "list_meeting_transcripts for the same meeting and match this value to read the "
            "transcript."
        )
    )

    @classmethod
    def from_recording(cls, recording: CallRecording, caller: str | None) -> Self:
        assert recording.id is not None, "Graph returned a recording with no id"
        organizer = _organizer_user_id(recording)
        return cls(
            recording_id=recording.id,
            started_at=recording.created_date_time,
            ended_at=recording.end_date_time,
            duration_seconds=_duration_seconds(recording),
            content_access=_content_access(organizer, caller),
            organizer_user_id=organizer,
            content_correlation_id=recording.content_correlation_id,
        )


class MeetingRecordings(BaseModel):
    status: RecordingStatus = Field(
        description=(
            "What was found and what to do next. One of:\n"
            "- `available` — recordings are listed with durations and access info.\n"
            "- `not_ready` — nothing arrived yet; window or meeting recently ended. Wait and "
            "retry. This is NOT 'the call was not recorded'. Microsoft publishes no availability "
            "SLA, so this tool infers timing and errs towards wait. A window that demonstrably "
            "passed is never reported this way.\n"
            "- `not_recorded` — the window is past; nothing there. The call was not recorded. "
            "Retrying will not help.\n"
            "- `scan_incomplete` — this meeting has more recordings than one call reads "
            f"({MAX_ARTIFACT_SCAN}) and none of the ones read fall in your window, so whether one "
            "exists there is NOT known. There is nothing to try: the window is applied to the "
            "recordings after Microsoft has answered, not by Microsoft while answering, so "
            "changing `started_after`/`started_before` reads the same recordings and returns this "
            "same status. Stop, and report that whether that occurrence was recorded could not be "
            "determined. Never report this as 'the call was not recorded'.\n"
            "- `meeting_not_found` — Microsoft matched the join URL to no meeting this user can "
            "see. Do not retry or rebuild the handle."
        )
    )
    meeting_id: str | None = Field(
        description=(
            "Resolved meeting's Graph id, or null if `status` is `meeting_not_found`. Opaque; no "
            "tool uses it."
        )
    )
    subject: str | None = Field(
        description=(
            "Meeting subject as Microsoft holds it. Confirms this is the right meeting. May differ "
            "from chat topic."
        )
    )
    meeting_type: str | None = Field(
        description=(
            "`scheduled`, `recurring`, `adhoc`, `meetNow`, `broadcast`, or null. When `recurring`, "
            "use `started_after`/`started_before` to reach one occurrence."
        )
    )
    started_at: datetime | None = Field(
        description=(
            "Meeting start. For a recurring series, Microsoft's single value for the whole series, "
            "not the occurrence you asked about."
        )
    )
    ended_at: datetime | None = Field(description="Meeting end (same caveat as `started_at`).")
    recordings: list[RecordingSummary] = Field(
        description=(
            "Recordings that fall inside the requested window, newest first. The order is over "
            f"every recording this call read (up to {MAX_ARTIFACT_SCAN}), not over one page of "
            "Microsoft's answer. For meetings with fewer recordings than that cap — all but series "
            "recorded daily for most of a year — the first entry is the latest of the window. Past "
            "the cap the first entry is the latest of what was READ; Microsoft returns this "
            "collection in its own order and offers no `$orderby`. Set `include_scan_completeness` "
            "to learn if the read reached the end. As many as `limit` means the window may hold "
            "older ones; fewer means the window holds no more than was read. Empty for every "
            "status other than `available`."
        )
    )
    scan_incomplete: bool | None = Field(
        description=(
            f"Whether the read stopped at {MAX_ARTIFACT_SCAN} recordings (true), read all (false), "
            "or null if not requested. Set only when `include_scan_completeness` is true. True "
            "means recordings ordered over those read, not all recordings. False means the order "
            "and any absence are exact. Status is always `scan_incomplete` when nothing was found "
            "and the read stopped short."
        )
    )


async def list_meeting_recordings(
    client: GraphServiceClient,
    *,
    handle: MeetingHandle,
    started_after: date | datetime | None,
    started_before: date | datetime | None,
    limit: int,
    include_scan_completeness: bool,
) -> MeetingRecordings:
    """Recordings of the meeting `handle` addresses.

    Two or three Graph requests: resolve, list, and — only when something was found — the caller id
    the organiser-only rule needs. Graph documents no date filter, so the window applies after.
    """
    assert 1 <= limit <= MAX_RECORDINGS, f"limit must be within 1..{MAX_RECORDINGS}, got {limit}"
    window = OccurrenceWindow.of(started_after, started_before)

    with graph_errors(TOOL_NAME):
        meeting = await resolve_meeting(client, handle)
        if meeting is None or meeting.id is None:
            return MeetingRecordings(
                status="meeting_not_found",
                meeting_id=None,
                subject=None,
                meeting_type=None,
                started_at=None,
                ended_at=None,
                recordings=[],
                scan_incomplete=False if include_scan_completeness else None,
            )
        with graph_step(STEP_RECORDINGS):
            first_page = await client.me.online_meetings.by_online_meeting_id(
                meeting.id
            ).recordings.get()
            assert first_page is not None, "Graph answered a recording listing with no collection"
            collected = await newest_in_window(first_page, client, window=window, limit=limit)
        found = collected.items
        # Only when it changes an answer: an empty listing has no organiser to compare anyone with.
        caller = (await identity.signed_in_user(client)).id if found else None

    return MeetingRecordings(
        status="available"
        if found
        else _absence(scan_stopped_short=collected.capped, settled=window.settled(meeting)),
        meeting_id=meeting.id,
        subject=meeting.subject,
        meeting_type=meeting.meeting_type,
        started_at=meeting.start_date_time,
        ended_at=meeting.end_date_time,
        recordings=[RecordingSummary.from_recording(recording, caller) for recording in found],
        scan_incomplete=collected.capped if include_scan_completeness else None,
    )


def _absence(*, scan_stopped_short: bool, settled: bool) -> RecordingStatus:
    """Which empty answer to give: stop, wait, or neither."""
    if scan_stopped_short:
        return "scan_incomplete"
    return "not_recorded" if settled else "not_ready"


def _organizer_user_id(recording: CallRecording) -> str | None:
    """Organiser's Entra object id, or None if Graph named nobody.

    TRAP: the identitySet's @odata.type is not always a known SDK type — Microsoft's own sample
    sends #Microsoft.Teams.GraphSvc.teamworkUserIdentity. An unknown discriminator deserializes to
    base identity, which still carries the id.
    """
    organizer = recording.meeting_organizer
    if organizer is None or organizer.user is None:
        return None
    return organizer.user.id


def _content_access(organizer: str | None, caller: str | None) -> ContentAccess:
    """Which side of the organiser-only rule the signed-in user is on.

    Guessing is wrong both ways, so a missing id is `unknown`. Ids compare case-insensitively: an
    Entra object id is a GUID and casing is not part of identity.
    """
    if organizer is None or caller is None:
        return "unknown"
    theirs = organizer.casefold() == caller.casefold()
    return "you_are_the_organizer" if theirs else "organizer_only"


def _duration_seconds(recording: CallRecording) -> float | None:
    """Recording length, or None if Graph did not send enough to compute one.

    A missing offset reads as Z, so no subtraction raises. Graph's negative offsets apply to content
    cue times, not to these fields, so a negative result is unknown rather than a duration.
    """
    began, ended = recording.created_date_time, recording.end_date_time
    if began is None or ended is None:
        return None
    seconds = (as_utc(ended) - as_utc(began)).total_seconds()
    return seconds if seconds >= 0 else None


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    # Closes over `transport` here; the default below holds this name, not a call (ruff's B008).
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List a Meeting's Recordings",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def list_recordings(
        meeting_uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Meeting handle from list_chats: `teams:///meetings/{join_web_url}`. Copy "
                    "verbatim; Microsoft matches character for character."
                ),
            ),
        ],
        started_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only recordings that began at or after this moment. Scope to one occurrence "
                    "of a recurring meeting. Shapes accepted: `2026-08-11T09:00:00+02:00` or "
                    "`...Z` (the instant named), `2026-08-11T09:00:00` (IS READ AS UTC), or "
                    "`2026-08-11` (that whole UTC day, first instant). Pass offset for local time "
                    "— 09:00 in Zurich is 07:00Z. A window with no recording inside is an answer "
                    "and not an error."
                )
            ),
        ] = None,
        started_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only recordings that began at or before this moment. Pair with "
                    "`started_after`. A bare `2026-08-11` means the END of that UTC day — same "
                    "date in both bounds is that whole day. A window whose end is already well "
                    "past reports not_recorded rather than not_ready."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RECORDINGS,
                description=(
                    f"How many recordings to return. Default 20, maximum {MAX_RECORDINGS}. These "
                    "are the NEWEST that many of the window. All recordings are read (up to "
                    f"{MAX_ARTIFACT_SCAN}, the call's whole cost) and ordered before this cuts "
                    "them. Past that cap they are the newest OF THE ONES READ, not the meeting's "
                    "newest. Raising limit does not read further past the cap."
                ),
            ),
        ] = 20,
        include_scan_completeness: Annotated[
            bool,
            Field(
                description=(
                    "Report whether the read reached the end of this meeting's recordings, as "
                    "`scan_incomplete`. Off by default. Use it to learn if the first recording "
                    "listed is the meeting's latest. You do not need it to trust an empty answer: "
                    "status already reports scan_incomplete."
                )
            ),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> MeetingRecordings:
        handle = meeting_handle(meeting_uri)
        if handle is None:
            raise ToolError(_NOT_A_MEETING_HANDLE)
        return await list_meeting_recordings(
            client,
            handle=handle,
            started_after=started_after,
            started_before=started_before,
            limit=limit,
            include_scan_completeness=include_scan_completeness,
        )
