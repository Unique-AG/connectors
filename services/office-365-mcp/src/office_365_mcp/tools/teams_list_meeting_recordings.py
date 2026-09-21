"""`teams_list_meeting_recordings` — did a call record, how long it ran, and who can get the file.

TRAP: no video ever comes back, and none is reachable anywhere in this connector. Graph serves a
recording as one MP4 byte stream, and `recordingContentUrl` opens only with this connector's own
token, so passing it on leaks a credential or does nothing. `tests/test_layering.py` rule 7 blocks
every module from addressing one recording, this file too.

Separate from `teams_list_meeting_transcripts` because Graph gates them independently, under
`OnlineMeetingRecording.Read.All` and `OnlineMeetingTranscript.Read.All`, and a default tenant has
the transcript gate shut. `content_correlation_id` links them.

Graph offers neither an `$orderby` nor any documented filterable property on this collection, so
rows are read up to MAX_ARTIFACT_SCAN and sorted before `limit` cuts them, and no date bound is
offered. Every row carries its own `started_at`, so one occurrence of a series is picked by reading
the answer.
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

STEP_RECORDINGS = "recordings"

# Entra redeems all three under one token or none.
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

# Graph-owned vocabularies (`meeting_type` here) stay `str`: Microsoft can add a member at any
# time. Bare assignment, not `type X = ...`: a PEP 695 alias publishes as a `$ref` into `$defs`,
# one hop away from the property a model reads.
RecordingStatus = Literal["available", "not_ready", "not_recorded", "meeting_not_found"]
ContentAccess = Literal["you_are_the_organizer", "organizer_only", "unknown"]

_DESCRIPTION = """\
Lists a Teams meeting's recordings, newest first, from the `meeting_uri` teams_list_chats \
reports. It reports whether a meeting was recorded, how long it ran, and who can download it. \
This tool returns no video, and none is reachable here. teams_list_meeting_transcripts \
reports the words instead.

Notes:
- Read `status` before you decide: `not_ready` means wait, not "the call was not recorded".
- An `organizer_only` recording exists but is out of reach. Never report it as missing.\
"""

# Local, not shared with teams_list_meeting_transcripts: `tests/test_layering.py` rule 4 forbids it.
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
        description="Recording's Graph id. This id is opaque, and no tool here accepts it as "
        + "an input."
    )
    started_at: datetime | None = Field(
        description=(
            "When recording began (Graph `createdDateTime`), not the meeting's start, or null "
            + "if Microsoft did not report one. For a recurring series, this timestamp "
            + "distinguishes one occurrence from another."
        )
    )
    ended_at: datetime | None = Field(
        description=(
            "When recording stopped (Graph `endDateTime`), or null if Microsoft did not report "
            + "one."
        )
    )
    duration_seconds: float | None = Field(
        description=(
            "Recording length in seconds (`ended_at` minus `started_at`). Microsoft publishes "
            + "no duration field, so this is derived and null if either timestamp is missing. "
            + "This is the recording's length, not the meeting's."
        )
    )
    content_access: ContentAccess = Field(
        description=(
            "Whether the signed-in user can download this recording. This is not about this "
            + "connector, which has no video. One of:\n"
            + "- `you_are_the_organizer` — the user is the organizer. Microsoft permits "
            + "download via Teams or SharePoint, but not here, unless an admin blocks it "
            + "tenant-wide.\n"
            + "- `organizer_only` — the user is not the organizer. Microsoft: 'Meeting "
            + "participants don't have permission to download meeting recordings' unless an "
            + "admin unblocks them. This is not a missing recording. The recording exists. "
            + "Only the video is out of reach.\n"
            + "- `unknown` — Microsoft named no organizer, so this cannot be determined."
        )
    )
    organizer_user_id: str | None = Field(
        description=(
            "Organizer's Entra object id, or null if Microsoft named no organizer. When "
            + "`content_access` is `organizer_only`, ask this person. Microsoft leaves the "
            + "organizer's display name null here, so this id is all there is. Comparable "
            + "with `get_me`'s `user_id`."
        )
    )
    content_correlation_id: str | None = Field(
        description=(
            "This id links this recording to its transcript, or null if Microsoft assigned "
            + "none. Pass it to teams_list_meeting_transcripts as `content_correlation_id`, "
            + "for the same meeting, to read the matching transcript."
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
            "What this tool found, and what to do next:\n"
            + "- `available` — this tool lists the recordings with durations and access.\n"
            + "- `not_ready` — nothing exists yet, and more can still arrive. Wait, then call "
            + "again. This is not the same as `not_recorded`. This tool never reports "
            + "`not_ready` for a meeting that demonstrably ended, however far in the future a "
            + "recurring series runs. This rule is inferred, because Microsoft publishes no "
            + "availability SLA.\n"
            + "- `not_recorded` — the meeting is over, and it was not recorded. A retry does "
            + "not help.\n"
            + "- `meeting_not_found` — no meeting that this user can see matched the join "
            + "URL. Do not retry or rebuild the handle."
        )
    )
    meeting_id: str | None = Field(
        description=(
            "Resolved meeting's Graph id, or null if `status` is `meeting_not_found`. This id "
            + "is opaque, and no tool here accepts it as input."
        )
    )
    subject: str | None = Field(
        description=(
            "Meeting subject as Microsoft holds it, or null if none is set. You can compare it "
            + "to make sure that this is the right meeting. It can differ from the chat topic."
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
            "Meeting start, or null if Microsoft reported none. For a recurring series, "
            + "Microsoft's single value for the whole series, not the occurrence asked about."
        )
    )
    ended_at: datetime | None = Field(
        description="Meeting end, or null on the same terms as `started_at`."
    )
    recordings: list[RecordingSummary] = Field(
        description=(
            "The meeting's recordings. This tool reads up to "
            + f"{MAX_ARTIFACT_SCAN} recordings and sorts them before `limit` cuts the list, "
            + "not just one page of Microsoft's answer. Past that cap, the first entry is the "
            + "latest of what this tool read, not the meeting's latest. If as many rows as "
            + "`limit` come back, older recordings can remain. Raise `limit` to reach "
            + "further, within that cap. Fewer rows than `limit` means none remain. Set "
            + "`include_scan_completeness` to learn whether the read reached the end. This "
            + "list is empty for every status other than `available`."
        )
    )
    scan_incomplete: bool | None = Field(
        description=(
            "Whether the read stopped at the scan cap (true) or reached the end (false). This "
            + "value is null unless `include_scan_completeness` was set."
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
    the organizer-only rule needs.
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

    TRAP: the identitySet's @odata.type is not always a known SDK type (Microsoft's own sample
    sends #Microsoft.Teams.GraphSvc.teamworkUserIdentity); an unknown discriminator deserializes
    to base identity, which still carries the id.
    """
    organizer = recording.meeting_organizer
    if organizer is None or organizer.user is None:
        return None
    return organizer.user.id


def _content_access(organizer: str | None, caller: str | None) -> ContentAccess:
    """Which side of the organizer-only rule the signed-in user is on.

    Ids compare case-insensitively: an Entra object id is a GUID and casing is not part of identity.
    """
    if organizer is None or caller is None:
        return "unknown"
    theirs = organizer.casefold() == caller.casefold()
    return "you_are_the_organizer" if theirs else "organizer_only"


def _duration_seconds(recording: CallRecording) -> float | None:
    """Recording length, or None if Graph did not send enough to compute one.

    Graph's negative offsets apply to content cue times, not to these fields, so a negative result
    is unknown rather than a duration.
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
                    "The meeting handle from teams_list_chats: `teams:///meetings/{join_web_url}`. "
                    + "Copy it verbatim. A `teams:///transcripts/...` handle is not valid here."
                ),
            ),
        ],
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RECORDINGS,
                description=(
                    f"How many recordings to return, at most {MAX_RECORDINGS}. This tool reads "
                    + f"up to {MAX_ARTIFACT_SCAN} and sorts them before this cuts the list. If "
                    + "you raise `limit`, you get more results, but only within that read."
                ),
            ),
        ] = 20,
        include_scan_completeness: Annotated[
            bool,
            Field(
                description=(
                    "Set this to true to learn whether the read reached the end, as "
                    + "`scan_incomplete`."
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
