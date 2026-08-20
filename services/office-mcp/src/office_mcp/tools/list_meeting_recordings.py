"""`list_meeting_recordings` — did a call record, how long it ran, and who may get the file.

TRAP: No video is returned or reachable anywhere in this connector. A Teams meeting runs 30 hours
max (https://learn.microsoft.com/en-us/microsoftteams/limits-specifications-teams). Graph serves a
recording as one MP4 byte stream. A model cannot watch video: an MP4 in text form is hundreds of
megabytes and answers nothing. This tool returns metadata and access rules only. It never returns
`recordingContentUrl` either: that link only opens with this connector's own token, so passing it
on leaks a credential or does nothing.

`tests/test_layering.py` rule 7 blocks every module from addressing one recording. That is the only
way to reach its bytes, so this file must stay inside the rule too.

The two artifacts (recordings and transcripts) need separate tools because Graph gates them
independently with separate permissions (OnlineMeetingRecording.Read.All vs
OnlineMeetingTranscript.Read.All). In a default tenant the transcript gate is shut. Combining both
in one tool would force the choice between failing a reachable recording or holding two incompatible
statuses. Each tool's refusal also names only its own missing permission, so an admin grants the
right one. The bridge between artifacts is `content_correlation_id` — Microsoft's own identifier
for "these two are the same call", present on both.

Newest first: Graph has no `$orderby` on this collection. Read up to MAX_ARTIFACT_SCAN, sort,
cut to `limit`. Stopping at `limit` before sorting returns an arbitrary subset sorted among itself.
Past the cap the first entry is the newest of what was READ; `scan_incomplete` says so.

The five statuses: `available` (newest first, with access rules), `not_ready` (nothing yet; window
or meeting recent), `not_recorded` (window is past; nothing there), `scan_incomplete` (more
recordings than one call reads; none in window; stop, no remedy), `meeting_not_found` (URL matched
no meeting this user sees; not proof of deletion — a meeting made outside a calendar, or one this
user was never invited to, answers the same way).

Duration is derived: Graph sends no duration field. It is `endDateTime - createdDateTime` from the
recording itself (not the meeting), null if either timestamp is missing. A recording started late
and stopped early is shorter than the meeting, and that is the honest answer.

TRAP: Organiser-only download. Microsoft: "Meeting participants don't have permission to download
meeting recordings" unless tenant admin unblocks them. Never report an unreachable recording as
missing — the existence and reachability are separate fields. Metadata access is wider than
download access: Microsoft gives recording metadata to every invited participant, but download
stays organiser-only. `content_access` says which side the signed-in user is on
(you_are_the_organizer / organizer_only / unknown). An admin can still block downloads tenant-wide
from SharePoint and OneDrive.
"""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Annotated

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

# This tool's own listing request and the walk that continues it. The meeting resolve
# before it is counted under `shared/meetings.py`'s own step, and the identity check under
# `shared/identity.py`'s — each Graph call is named by the module that owns it.
STEP_RECORDINGS = "recordings"

# Three permissions: meeting resolve, recordings read, and identity check (to answer the
# organiser-only rule). Entra redeems all under one token or none. Permission names are in
# shared/meetings.py because they are referenced twice and must never be wrong.
GRAPH_PERMISSIONS: tuple[str, ...] = (
    MEETING_PERMISSION,
    RECORDING_PERMISSION,
    identity.GRAPH_PERMISSION,
)

# One call that reaches Graph, read by `tools/__init__.py` into the coverage table
# `tests/test_error_mapping.py` refuses every registered tool from. The ids are invented; what
# matters is that the shape is one this tool accepts, because an argument it rejects is refused here
# and never reaches Graph, which would leave its Graph refusals unchecked.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "meeting_uri": "teams:///meetings/https%3A%2F%2Fteams.microsoft.invalid%2Fl%2Fmeetup-join"
    + "%2F19%253ameeting_TjAwMDAwMDAwMDAwMA%2540thread.v2%2F0"
}

# Max recordings per call. A one-off meeting has 1–2; a series has 1 per recorded occurrence.
# Graph sets no ceiling on `$top`; this limit is ours.
MAX_RECORDINGS = 50

_DESCRIPTION = f"""\
List a Teams meeting's recordings: whether it was recorded, how long, and whether the signed-in \
user may download it.

**No video is returned or reachable anywhere in this connector.** A Teams meeting runs 30 hours \
max. Graph serves a recording as one MP4 byte stream. A model cannot watch video, so returning \
the file would be neither possible nor useful. This tool returns metadata and access rules only.

Call list_meeting_transcripts for the same meeting when you need the words. Use \
`content_correlation_id` to match a recording with its transcript — that is Microsoft's own \
identifier for "these two are the same call".

**Read `status` before anything else. Five values, five actions:**
- `available` — recordings are listed, newest first, with durations and access info.
- `not_ready` — nothing is there yet for the window you asked; the window or meeting just ended. \
Wait and call again later. This is NOT "the call was not recorded". Microsoft publishes no \
availability SLA, so this tool infers timing and errs towards wait.
- `not_recorded` — the window is past; nothing is there. The call was not recorded. Retrying will \
not help.
- `scan_incomplete` — this meeting has more recordings than one call reads \
({MAX_ARTIFACT_SCAN}). None read fall in your window, so whether one exists there is not known. \
The window applies after Microsoft answers (not in the request), so narrower \
`started_after`/`started_before` reads the same recordings and returns this same answer. \
There is nothing to try. Stop here. Never report it as "the call was not recorded".
- `meeting_not_found` — Microsoft matched the join URL to no meeting this user can see.

**`content_access` says whether this user may download the video.** It is not about this \
connector, which has no video. Microsoft's rule is ORGANISER-ONLY under delegated access: \
"Meeting participants don't have permission to download meeting recordings" unless a tenant \
admin has unblocked participants. Never report an `organizer_only` recording as a missing one — \
it exists; the video is out of reach. See `organizer_user_id` to learn who to ask. The three \
values are you_are_the_organizer / organizer_only / unknown. An admin can still block recording \
downloads tenant-wide from SharePoint and OneDrive.

For `duration_seconds`: Microsoft publishes no duration property. It is computed as endDateTime \
minus createdDateTime from the recording itself (not the meeting). It is null if either timestamp \
is missing. A recording started late and stopped early is shorter than the meeting.

For recurring meetings, use `started_after`/`started_before` to reach one occurrence. A whole \
series is one meeting to Microsoft, so every occurrence's recording is in this collection. Both \
bounds take a date (that whole UTC day) or a timestamp with or without offset — no offset reads \
as UTC.

Recordings are NOT behind the tenant-wide Teams switch for transcript access, so this tool can \
succeed where list_meeting_transcripts is refused outright. Recordings need their own \
admin-consented permission ({RECORDING_PERMISSION}); refusal names it.\
"""

# `tests/test_layering.py` rule 4 forbids one tool file from importing another, so this text
# stays local rather than being shared with list_meeting_transcripts's own refusal.
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
    content_access: str = Field(
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


class MeetingRecordings(BaseModel):
    status: str = Field(
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
    """Recordings of the meeting `handle` addresses and what to do about them.

    Two or three Graph requests: resolve URL, list collection, and (if found) get caller id
    to answer the organiser-only rule.

    Window is applied after fetching, not as `$filter`. Graph has no `$orderby` on this collection
    and no documented date filter. The window decides both which recordings are kept and what an
    empty answer means.
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
        # Asked for last and only when it changes an answer: with nothing to report there is no
        # organiser to compare anybody with, and the request would be spent on every empty listing.
        # Reused from shared/identity.py rather than a second GET /me under a different projection.
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
        recordings=[_summary(recording, caller) for recording in found],
        scan_incomplete=collected.capped if include_scan_completeness else None,
    )


def _absence(*, scan_stopped_short: bool, settled: bool) -> str:
    """Which empty answer to give: stop, wait, or neither."""
    if scan_stopped_short:
        return "scan_incomplete"
    return "not_recorded" if settled else "not_ready"


def _summary(recording: CallRecording, caller: str | None) -> RecordingSummary:
    assert recording.id is not None, "Graph returned a recording with no id"
    organizer = _organizer_user_id(recording)
    return RecordingSummary(
        recording_id=recording.id,
        started_at=recording.created_date_time,
        ended_at=recording.end_date_time,
        duration_seconds=_duration_seconds(recording),
        content_access=_content_access(organizer, caller),
        organizer_user_id=organizer,
        content_correlation_id=recording.content_correlation_id,
    )


def _organizer_user_id(recording: CallRecording) -> str | None:
    """Organiser's Entra object id, or None if Graph named nobody.

    Graph sends the organiser as an identitySet. The @odata.type discriminator
    on the user inside is not always a known SDK type — Microsoft's sample sends
    #Microsoft.Teams.GraphSvc.teamworkUserIdentity rather than #microsoft.graph.*.
    Unknown discriminators deserialize safely to base identity, which still carries
    the id, so subtype does not matter.
    """
    organizer = recording.meeting_organizer
    if organizer is None or organizer.user is None:
        return None
    return organizer.user.id


def _content_access(organizer: str | None, caller: str | None) -> str:
    """Which side of the organiser-only rule the signed-in user is on.

    None for either id means it cannot be told. Guessing either way is wrong:
    claiming organizer promises a download Microsoft refuses; claiming participant
    sends the caller to ask someone who already has access. Ids are compared
    case-insensitively — an Entra object id is a GUID; casing is not part of
    identity.
    """
    if organizer is None or caller is None:
        return "unknown"
    theirs = organizer.casefold() == caller.casefold()
    return "you_are_the_organizer" if theirs else "organizer_only"


def _duration_seconds(recording: CallRecording) -> float | None:
    """Recording length or None if Graph did not send enough data.

    Both timestamps resolve on UTC assumption: missing offset reads as Z, so
    no subtraction raises. Negative result is not a duration — Graph's negative
    offsets apply to content cue times, not these fields. Report negative as
    unknown rather than as a negative number.
    """
    began, ended = recording.created_date_time, recording.end_date_time
    if began is None or ended is None:
        return None
    seconds = (as_utc(ended) - as_utc(began)).total_seconds()
    return seconds if seconds >= 0 else None


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Register this tool with the shared Graph transport.

    The tool borrows `transport` per call and does not own it. `create_app` closes it on
    shutdown.
    """
    # Built here because this is where `transport` is, and named rather than called in the default.
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
