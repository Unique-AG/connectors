"""`teams_list_meeting_recordings` — did a call record, how long it ran, and who can get the file.

TRAP: no video ever comes back, and none of it is reachable anywhere in this connector. A Teams
meeting runs 30 hours max
(https://learn.microsoft.com/en-us/microsoftteams/limits-specifications-teams) and Graph serves
a recording as one MP4 byte stream. `recordingContentUrl` is never returned either: that link opens
only with this connector's own token, so passing it on leaks a credential or does nothing.
`tests/test_layering.py` rule 7 blocks every module from addressing one recording, this file too.

Separate from `teams_list_meeting_transcripts` because Graph gates them independently, under
`OnlineMeetingRecording.Read.All` and `OnlineMeetingTranscript.Read.All`, and a default tenant has
the transcript gate shut. Combining them into one tool forces a choice: fail a reachable
recording, or hold two incompatible statuses. `content_correlation_id` links them.

Newest first: Graph has no `$orderby` on this collection. Read up to MAX_ARTIFACT_SCAN, sort, then
cut to `limit`. Stopping at `limit` before sorting returns an arbitrary subset sorted among itself.

**No date window, deliberately.** This tool used to take `started_after`/`started_before` and apply
them to the rows after the fetch. They are gone. The collection enumerates `$select`, `$filter` and
`$top`, so `$filter` is documented by name — but it names no filterable *property*, and
`createdDateTime` appears in no `$filter` context for `callRecording`. Offering a date therefore
published a filter this connector performed itself. Every row still carries its own `started_at`,
so one occurrence of a series is picked by reading the answer. See
`teams_list_meeting_transcripts` for the second reason a server-side date bound was refused.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, Self

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.call_recording import CallRecording
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared import identity
from office_365_mcp.shared.handles import MeetingHandle, meeting_handle
from office_365_mcp.shared.meetings import (
    MAX_ARTIFACT_SCAN,
    MEETING_PERMISSION,
    RECORDING_PERMISSION,
    newest_of,
    resolve_meeting,
    settled,
)
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import as_utc

TOOL_NAME = "teams_list_meeting_recordings"

# The meeting resolve counts under `shared/meetings.py`'s step and the identity check under
# `shared/identity.py`'s, so this names only the listing request and the walk that continues it.
STEP_RECORDINGS = "recordings"

# Meeting resolve, recordings read, and the identity check the organizer-only rule needs. Entra
# redeems all three under one token or none. The names live in `shared/meetings.py`.
GRAPH_PERMISSIONS: tuple[str, ...] = (
    MEETING_PERMISSION,
    RECORDING_PERMISSION,
    identity.GRAPH_PERMISSION,
)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "meeting_uri": "teams:///meetings/https%3A%2F%2Fteams.microsoft.invalid%2Fl%2Fmeetup-join"
    + "%2F19%253ameeting_TjAwMDAwMDAwMDAwMA%2540thread.v2%2F0"
}

# Graph sets no ceiling on `$top`, so this limit is ours.
MAX_RECORDINGS = 50

# Both vocabularies are this connector's, not Microsoft's, so they are closed and publish as enums
# in the output schema rather than as bare strings a model has to mine out of the prose. Graph-owned
# vocabularies (`meeting_type` here) stay `str`, because Microsoft can add a member at any time.
# Bare assignment, not `type X = ...`: PEP 695 aliases publish as a `$ref` into `$defs`, which puts
# the values one hop away from the property a model reads.
RecordingStatus = Literal["available", "not_ready", "not_recorded", "meeting_not_found"]
ContentAccess = Literal["you_are_the_organizer", "organizer_only", "unknown"]

_DESCRIPTION = """\
List a Teams meeting's recordings from the `meeting_uri` teams_list_chats reports. Call it to \
learn whether a meeting was recorded, how long it ran, and who can download it — no video is \
returned or reachable here; for the words, call teams_list_meeting_transcripts. Read `status` \
first: `not_ready` means wait, not "the call was not recorded". An `organizer_only` recording \
exists but is out of reach: never report it as missing. Returns `status` and each recording's \
times, duration, and access.\
"""

# Local, not shared with teams_list_meeting_transcripts: `tests/test_layering.py` rule 4 forbids
# that.
_NOT_A_MEETING_HANDLE = (
    "teams_list_meeting_recordings takes the `meeting_uri` from teams_list_chats: "
    + "teams:///meetings/{join_web_url}. This is not one. Call teams_list_chats, find the meeting "
    + "chat, "
    + "and pass its `meeting_uri` verbatim. A `teams:///transcripts/...` handle belongs to "
    + "teams_read_transcript. No recording is addressable here. Retrying this value will fail "
    + "identically."
)


class RecordingSummary(BaseModel):
    recording_id: str = Field(
        description=(
            "Recording's Graph id. This id is opaque. No tool here uses it. This connector has "
            + "no recording handle."
        )
    )
    started_at: datetime | None = Field(
        description=(
            "When recording began (Microsoft's `createdDateTime`), not the meeting's. For "
            + "recurring meetings, this distinguishes one occurrence from another."
        )
    )
    ended_at: datetime | None = Field(
        description="When recording stopped (Microsoft's `endDateTime`)."
    )
    duration_seconds: float | None = Field(
        description=(
            "Recording length: `ended_at - started_at`. Microsoft publishes no duration field, so "
            + "this is derived and null if either timestamp is missing. It is the recording's "
            + "length, not the meeting's."
        )
    )
    content_access: ContentAccess = Field(
        description=(
            "Whether the SIGNED-IN user can download this recording. Not about this connector "
            + "(which has no video). One of:\n"
            + "- `you_are_the_organizer` — user is the organizer. Microsoft permits download in "
            + "Teams or SharePoint, not here. Admin can still block tenant-wide.\n"
            + "- `organizer_only` — user is not the organizer. Microsoft: 'Meeting participants "
            + "don't have permission to download meeting recordings' unless admin unblocks them. "
            + "This is NOT a missing recording: it exists, but the video is out of reach.\n"
            + "- `unknown` — Microsoft named no organizer, so this tool cannot tell which above "
            + "applies."
        )
    )
    organizer_user_id: str | None = Field(
        description=(
            "Organizer's Entra object id, or null. The person to ask when `content_access` is "
            + "`organizer_only`. Microsoft leaves the organizer's display name null on this "
            + "resource, so this id is all there is. Comparable with get_me's `user_id` and "
            + "message "
            + "sender `user_id`."
        )
    )
    content_correlation_id: str | None = Field(
        description=(
            "Microsoft's identifier linking this recording to its transcript. Call "
            + "teams_list_meeting_transcripts for the same meeting and match this value to read "
            + "the "
            + "transcript."
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
            + "- `available` — recordings are listed with durations and access info.\n"
            + "- `not_ready` — nothing arrived yet. The meeting recently ended. Wait "
            + "and retry. This is NOT 'the call was not recorded'. Microsoft publishes no "
            + "availability SLA, so this tool infers timing and errs towards wait. A meeting that "
            + "demonstrably ended is never reported this way.\n"
            + "- `not_recorded` — the meeting is over. Nothing is there. The call was not "
            + "recorded. Retrying will not help.\n"
            + "- `meeting_not_found` — Microsoft matched the join URL to no meeting this user can "
            + "see. Do not retry or rebuild the handle."
        )
    )
    meeting_id: str | None = Field(
        description=(
            "Resolved meeting's Graph id, or null if `status` is `meeting_not_found`. This id is "
            + "opaque. No tool uses it."
        )
    )
    subject: str | None = Field(
        description=(
            "Meeting subject as Microsoft holds it. Confirms this is the right meeting. This can "
            + "differ from chat topic."
        )
    )
    meeting_type: str | None = Field(
        description=(
            "`scheduled`, `recurring`, `adhoc`, `meetNow`, `broadcast`, or null. When `recurring`, "
            + "read each row's `started_at` to tell one occurrence from another."
        )
    )
    started_at: datetime | None = Field(
        description=(
            "Meeting start. For a recurring series, Microsoft's single value for the whole series, "
            + "not the occurrence you asked about."
        )
    )
    ended_at: datetime | None = Field(description="Meeting end (same caveat as `started_at`).")
    recordings: list[RecordingSummary] = Field(
        description=(
            "The meeting's recordings, newest first. The order is over "
            + f"every recording this call read (up to {MAX_ARTIFACT_SCAN}), not over one page of "
            + "Microsoft's answer. For meetings with fewer recordings than that cap — all but "
            + "series "
            + "recorded daily for most of a year — the first entry is the latest that was read. "
            + "Past "
            + "the cap the first entry is the latest of what was READ. Microsoft returns this "
            + "collection in its own order and offers no `$orderby`. Set "
            + "`include_scan_completeness` "
            + "to learn if the read reached the end. As many as `limit` means the meeting can "
            + "hold older ones. Fewer means it holds no more than was read. Empty for every "
            + "status other than `available`."
        )
    )
    scan_incomplete: bool | None = Field(
        description=(
            f"Whether the read stopped at {MAX_ARTIFACT_SCAN} recordings (true), read all (false), "
            + "or null if not requested. Set only when `include_scan_completeness` is true. True "
            + "means recordings ordered over those read, not all recordings. False means the "
            + "order and any absence are exact."
        )
    )


async def teams_list_meeting_recordings(
    client: GraphServiceClient,
    *,
    handle: MeetingHandle,
    limit: int,
    include_scan_completeness: bool,
) -> MeetingRecordings:
    """Recordings of the meeting `handle` addresses.

    Two or three Graph requests: resolve, list, and — only when something was found — the caller id
    the organizer-only rule needs. Graph names no filterable date here, so this tool offers none.
    """
    assert 1 <= limit <= MAX_RECORDINGS, f"limit must be within 1..{MAX_RECORDINGS}, got {limit}"

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
            collected = await newest_of(first_page, client, limit=limit)
        found = collected.items
        # Only when it changes an answer: an empty listing has no organizer to compare anyone with.
        caller = (await identity.signed_in_user(client)).id if found else None

    return MeetingRecordings(
        status="available" if found else _absence(settled=settled(meeting)),
        meeting_id=meeting.id,
        subject=meeting.subject,
        meeting_type=meeting.meeting_type,
        started_at=meeting.start_date_time,
        ended_at=meeting.end_date_time,
        recordings=[RecordingSummary.from_recording(recording, caller) for recording in found],
        scan_incomplete=collected.capped if include_scan_completeness else None,
    )


def _absence(*, settled: bool) -> RecordingStatus:
    """Which empty answer to give: stop, wait, or neither."""
    return "not_recorded" if settled else "not_ready"


def _organizer_user_id(recording: CallRecording) -> str | None:
    """Organizer's Entra object id, or None if Graph named nobody.

    TRAP: the identitySet's @odata.type is not always a known SDK type — Microsoft's own sample
    sends #Microsoft.Teams.GraphSvc.teamworkUserIdentity. An unknown discriminator deserializes to
    base identity, which still carries the id.
    """
    organizer = recording.meeting_organizer
    if organizer is None or organizer.user is None:
        return None
    return organizer.user.id


def _content_access(organizer: str | None, caller: str | None) -> ContentAccess:
    """Which side of the organizer-only rule the signed-in user is on.

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
                    "Meeting handle from teams_list_chats: `teams:///meetings/{join_web_url}`. "
                    + "Copy it verbatim. Microsoft matches character for character."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RECORDINGS,
                description=(
                    f"How many recordings to return. Default 20, maximum {MAX_RECORDINGS}. These "
                    + "are the NEWEST that many of the meeting. All recordings are read (up to "
                    + f"{MAX_ARTIFACT_SCAN}, the call's whole cost) and ordered before this cuts "
                    + "them. Past that cap they are the newest OF THE ONES READ, not the meeting's "
                    + "newest. Raising limit does not read further past the cap."
                ),
            ),
        ] = 20,
        include_scan_completeness: Annotated[
            bool,
            Field(
                description=(
                    "Report whether the read reached the end of this meeting's recordings, as "
                    + "`scan_incomplete`. Off by default. Use it to learn if the first recording "
                    + "listed is the meeting's latest, and whether an older one may sit beyond "
                    + "the cap."
                )
            ),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> MeetingRecordings:
        handle = meeting_handle(meeting_uri)
        if handle is None:
            raise ToolError(_NOT_A_MEETING_HANDLE)
        return await teams_list_meeting_recordings(
            client,
            handle=handle,
            limit=limit,
            include_scan_completeness=include_scan_completeness,
        )
