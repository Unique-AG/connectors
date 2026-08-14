"""Meeting recordings: whether a call was recorded, how long it ran, and who may get at the video.

Nothing here returns video, and nothing in this connector can. A Teams meeting runs up to thirty
hours (https://learn.microsoft.com/en-us/microsoftteams/limits-specifications-teams), Graph serves
`…/recordings/{id}/content` as one inline `video/mp4` byte stream with no ranged-fetch contract
documented on that path, and a model cannot watch video: an MP4 encoded into a tool result is
hundreds of megabytes of text that answers nothing. `recordingContentUrl` is no better — it is a
Graph URL that only this connector's bearer token opens, so handing it to a caller is either
useless or a token leak. What is worth returning is what a caller can act on: that a recording
exists, when it ran and for how long, whether Microsoft would let this user download it, and which
transcript is the same call. `tests/test_layering.py` rule 10 is the ratchet on that decision — no
module here may address a single recording, which is the only way to reach its bytes.

## Why this is a sibling of `list_meeting_transcripts` and not one artifact tool

The two answer about the same meeting from the same handle over the same window, so one tool
listing both artifacts is the obvious shape and it is the wrong one, for a reason that is
Microsoft's rather than ours: **the two are gated independently, and one gate is shut by default.**
Graph access to transcripts is a tenant-wide Teams switch that is off until an administrator turns
it on, and while it is off every transcript call answers `403` with no request-side workaround —
whereas that control "applies to transcript resources only; recording subscriptions are
unaffected" (https://learn.microsoft.com/en-us/graph/teams-changenotifications-callrecording-and-calltranscript),
and neither recordings reference page mentions a tenant switch or any inner error code of its own.
The two delegated permissions are separate and separately admin-consented, too
(`OnlineMeetingTranscript.Read.All`, `OnlineMeetingRecording.Read.All`), so a tenant can grant
either without the other.

A combined tool in a default tenant therefore has two options and both are bad: fail the whole
call, answering nothing about a recording that was perfectly reachable, or carry a status per
artifact — two verdicts, two refusals-as-data, and the "read `status` first" shape that makes the
transcript answer actionable replaced by something a model has to unpick. It would also blunt the
one thing a 403 here is good for: every tool in this connector names only the permissions its own
request was made under, so an administrator is sent after the permission that was actually missing.

What is shared is shared for real rather than copied: the meeting handle, the join-URL resolve, the
occurrence window and the windowed newest-first walk (`newest_in_window`, which is also where both
listers' `scan_incomplete` and their "the scan stopped short, so nothing about absence is known"
verdict come from) all live in `transcripts`, which owns that handle family (layering rule 9), and
this module imports them. The bridge between the two answers is `content_correlation_id`,
Microsoft's own "unique identifier that links the transcript with its corresponding recording" —
present on both artifacts, so a model holding one list can pair it with the other.

## Duration is derived, because Graph does not publish one

`callRecording` carries `id`, `meetingId`, `callId`, `createdDateTime`, `endDateTime`,
`contentCorrelationId`, `meetingOrganizer` and `recordingContentUrl` — and no duration, no size and
no media type (https://learn.microsoft.com/en-us/graph/api/resources/callrecording). So the "how
long" half of the question is `endDateTime - createdDateTime` and nothing better exists; where
Graph sent either timestamp as null, `duration_seconds` is null rather than a guess. Both bounds
are the recording's own, which is not the meeting's: a recording started ten minutes late and
stopped early is shorter than the meeting, and that is the honest answer to "how long is the
recording".

## The organiser-only constraint, and why the caller's own id is fetched to report it

Microsoft is explicit and this is the fact that has to reach a model:

> In delegated permission scenarios, getting callRecording content is supported only for the
> meeting organizer. Meeting participants don't have permission to download meeting recordings.
> … For online meetings, tenant admins can unblock meeting participants to download meeting
> recordings. (https://learn.microsoft.com/en-us/graph/api/callrecording-get)

Note the asymmetry with the *metadata*, which the same page says "is also available to users who
are part of the meeting calendar invite": for most meetings a participant asks about, the recording
is visible and its content is out of reach. Answering "there is no recording" in that case would be
a wrong answer a caller cannot detect, so the existence and the reachability are separate fields and
an unreachable recording is always listed.

Reporting the constraint as a constant string on every recording would say nothing, and reporting
only the organiser's identity would not answer the question either: Graph's own documented samples
return `meetingOrganizer.user.displayName` as null, so a model would be handed a bare object id to
compare against something it has not fetched. So the comparison is made here — one extra
`GET /me`, under `User.Read`, which needs no admin consent and which this connector already asks
for at sign-in — and `content_access` says which side of the constraint the signed-in user is on.
It is asked for only when there is a recording to say it about, so the common "nothing was
recorded" answer still costs two requests.

`content_access` is deliberately not a promise about a download: an administrator can block
recording downloads tenant-wide from SharePoint and OneDrive
(https://learn.microsoft.com/en-us/MicrosoftTeams/block-download-meeting-recording), and can
equally have unblocked participants. It says what Microsoft's documented default makes of *this*
user, which is the most a caller can be told without guessing.
"""

from datetime import date, datetime

from msgraph.generated.models.call_recording import CallRecording
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.features import identity
from office_mcp.features.transcripts import (
    MAX_ARTIFACT_SCAN,
    MEETING_PERMISSION,
    MeetingHandle,
    OccurrenceWindow,
    as_utc,
    newest_in_window,
    resolve_meeting,
)
from office_mcp.graph_client import graph_errors

# The delegated permission this module's own request needs. Admin-consented, like transcript
# access and separately from it — a tenant may grant either without the other, which is why the
# two artifacts are listed by two tools that redeem two different tokens.
RECORDING_PERMISSION = "OnlineMeetingRecording.Read.All"

# What listing a meeting's recordings costs: resolving the join URL, reading the collection, and
# finding out who the caller is so that the organiser-only constraint can be answered rather than
# merely recited. In that order, under one token — Entra redeems them together or not at all.
LISTING_PERMISSIONS: tuple[str, ...] = (
    MEETING_PERMISSION,
    RECORDING_PERMISSION,
    identity.GRAPH_PERMISSION,
)

# How many recordings one listing returns. A one-off meeting has one (or two, where somebody
# stopped and restarted); a recurring series accumulates one per occurrence in the same collection,
# which is what makes a window necessary. Graph documents `$top` here but publishes no ceiling, so
# this is ours, and it is the transcript lister's for the same reason.
MAX_RECORDINGS = 50


class RecordingSummary(BaseModel):
    recording_id: str = Field(
        description=(
            "The recording's Graph id. Opaque, and no tool here takes it: this connector never "
            + "returns or fetches recording video, so there is no handle for one and nothing to "
            + "pass it to. Report it only if a person needs to identify the file elsewhere."
        )
    )
    started_at: datetime | None = Field(
        description=(
            "When recording began (Microsoft's `createdDateTime`) — the recording's own start, not "
            + "the meeting's. For a recurring meeting this is what tells one occurrence from "
            + "another: every occurrence's recording lands in the same collection and Microsoft "
            + "gives no occurrence id."
        )
    )
    ended_at: datetime | None = Field(
        description="When recording stopped (Microsoft's `endDateTime`)."
    )
    duration_seconds: float | None = Field(
        description=(
            "How long the recording runs, computed as `ended_at - started_at`. Microsoft publishes "
            + "no duration, size or media-type property on a recording, so this is derived and it "
            + "is null when either timestamp is missing — there is no better source and inventing "
            + "one would be a fabrication. It is the recording's length rather than the meeting's."
        )
    )
    content_access: str = Field(
        description=(
            "Whether Microsoft would let the SIGNED-IN user download this recording's video. It "
            + "says nothing about this connector, which never returns video at all. One of:\n"
            + "- `you_are_the_organizer` — the signed-in user organised the meeting, and Microsoft "
            + "permits the organiser to download the recording (in Teams or SharePoint, not here). "
            + "An administrator can still have blocked recording downloads tenant-wide.\n"
            + "- `organizer_only` — the signed-in user is not the organiser. Microsoft: 'Meeting "
            + "participants don't have permission to download meeting recordings', unless a tenant "
            + "administrator has unblocked participants. `organizer_user_id` says whose it is. "
            + "This is NOT a missing recording: the recording exists and its details here are "
            + "real, so say it exists and that the video is out of this user's reach, and offer "
            + "the transcript instead.\n"
            + "- `unknown` — Microsoft named no organiser for this recording, so which of the two "
            + "above applies cannot be told."
        )
    )
    organizer_user_id: str | None = Field(
        description=(
            "The meeting organiser's Microsoft Entra object id, or null where Microsoft named "
            + "nobody. The person to ask for the video when `content_access` is `organizer_only`. "
            + "Microsoft leaves the organiser's display name null on this resource, so this id is "
            + "all there is — it is comparable with the `user_id` get_me returns and with a "
            + "message sender's `user_id`, and a name is not."
        )
    )
    content_correlation_id: str | None = Field(
        description=(
            "Microsoft's identifier linking this recording to the transcript of the same call. "
            + "This is the bridge to the readable artifact: call list_meeting_transcripts for the "
            + "same meeting and the transcript carrying this same value is this call, so a "
            + "recording nobody may download can still be answered from its transcript."
        )
    )


class MeetingRecordings(BaseModel):
    status: str = Field(
        description=(
            "What was found, and therefore what to do next. Exactly one of:\n"
            + "- `available` — `recordings` lists them, with their durations and whether the "
            + "signed-in user may download each. No video is returned or reachable here.\n"
            + "- `not_ready` — nothing is there for the window you asked about and something may "
            + "still arrive: that window has only just closed, or you asked for no window and the "
            + "meeting itself has not ended or ended recently. Microsoft publishes no availability "
            + "SLA and no 'processing' status for a recording, so this is inferred: it means wait "
            + "and ask again later, and it is NOT evidence that the call was never recorded. A "
            + "window that has demonstrably passed is never reported this way, however far in the "
            + "future a recurring series runs.\n"
            + "- `not_recorded` — the window is over, nothing is there, and nothing is expected: "
            + "the call was not recorded. Retrying will not change this. One other cause looks "
            + "identical and cannot be distinguished: Microsoft's meeting-artifact APIs stop "
            + "serving a meeting once it expires (about 60 days after a one-off), so a recording "
            + "that once existed can read as never having existed.\n"
            + "- `scan_incomplete` — this meeting has more recordings than one call reads "
            + f"({MAX_ARTIFACT_SCAN}) and none of the ones read fall in your window, so whether "
            + "one exists there is NOT known and is not being claimed either way. There is nothing "
            + "to try: the window is applied to the recordings after Microsoft has answered, not "
            + "by Microsoft while answering, so changing `started_after`/`started_before` — "
            + "narrower, wider, anything — reads the same recordings and returns this same status. "
            + "Stop, and report that whether that occurrence was recorded could not be determined. "
            + "Never report this as 'the call was not recorded', and do not ask again.\n"
            + "- `meeting_not_found` — Microsoft matched the join URL to no meeting this user can "
            + "see. Not an error and not proof the meeting is gone; a meeting created outside a "
            + "calendar, or one this user was never invited to, answers the same way. Do not retry "
            + "and do not rebuild the handle."
        )
    )
    meeting_id: str | None = Field(
        description=(
            "The resolved meeting's Graph id, or null when `status` is `meeting_not_found`. "
            + "Opaque, and no tool here takes it."
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
            + "Microsoft, so every occurrence's recording is in this one collection and "
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
    recordings: list[RecordingSummary] = Field(
        description=(
            "The recordings of this meeting that fall inside the requested window, newest first. "
            + "The order is over every recording this call read rather than over one page of "
            + f"Microsoft's answer, and one call reads up to {MAX_ARTIFACT_SCAN} of them. For a "
            + "meeting with no more recordings than that — every meeting bar a series recorded "
            + "daily for most of a year — those are all of them, so the first entry is the latest "
            + "recording of the window outright, which for a recurring series is how to reach the "
            + "most recent occurrence. Past that cap the first entry is the latest of what was "
            + "READ: Microsoft returns this collection in an order of its own and offers no way to "
            + "ask for the newest, so a newer recording can sit among the ones never read; set "
            + "`include_scan_completeness` when the answer turns on that. As many entries as "
            + "`limit` means the window may hold older ones too — raise `limit`, up to "
            + f"{MAX_RECORDINGS} — and fewer than `limit` means these are the whole window. There "
            + "is no cursor. Empty for every status other than `available`."
        )
    )
    scan_incomplete: bool | None = Field(
        description=(
            "Whether the read stopped at the cap on how many of this meeting's recordings one call "
            + f"looks through ({MAX_ARTIFACT_SCAN}), or null when `include_scan_completeness` was "
            + "not set — which is the default, because it only matters for a meeting with more "
            + "recordings than that.\n"
            + "True means `recordings` is ordered over the ones READ and not over the meeting, so "
            + "the first entry may not be the meeting's latest and nothing here reads further: no "
            + "argument to this tool changes it, the window being applied after the read. False "
            + "means the whole collection was read, so the order and any absence within it are "
            + "exact. This says nothing about `limit` — that the window held more than you asked "
            + "for is what a full `recordings` list means. You never need this to tell whether an "
            + "empty answer is trustworthy: `status` is `scan_incomplete` in exactly that case."
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
    """The recordings of the meeting `handle` addresses, and what a caller should do about them.

    Two Graph requests, or three where something was found: resolve the join URL, list the
    collection, and — only then — ask who the caller is, which is what turns Microsoft's
    organiser-only rule from a sentence into an answer about this user.

    The listing goes out bare and the window is applied while paging rather than as a `$filter`.
    Graph documents `$select`, `$filter` and `$top` on this collection and no `$orderby`, and it
    documents exactly one filterable property by example, `contentCorrelationId`
    (https://learn.microsoft.com/en-us/graph/api/callrecording-get, Example 5) — never a date — so
    a server-side date bound would be unverified, and a wrong one returns nothing rather than
    failing. The same window then decides both which recordings are kept and what an empty answer
    means, exactly as it does for transcripts — and, exactly as there, it is no route further into
    a collection the scan cap cut short, because it is applied to what came back.

    `include_scan_completeness` decides only whether `scan_incomplete` is reported and never what is
    read, on the same reasoning as the transcript lister: it answers about one rare meeting shape,
    while `status` reports a scan that stopped short whenever it is the difference between "nobody
    recorded it" and "nobody looked".
    """
    assert 1 <= limit <= MAX_RECORDINGS, f"limit must be within 1..{MAX_RECORDINGS}, got {limit}"
    window = OccurrenceWindow.of(started_after, started_before)

    with graph_errors():
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
        first_page = await client.me.online_meetings.by_online_meeting_id(
            meeting.id
        ).recordings.get()
        assert first_page is not None, "Graph answered a recording listing with no collection"
        collected = await newest_in_window(first_page, client, window=window, limit=limit)
        found = collected.items
        # Asked for last and only when it changes an answer: with nothing to report there is no
        # organiser to compare anybody with, and the request would be spent on every empty listing.
        caller = (await identity.get_signed_in_user(client)).user_id if found else None

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
    """Which empty answer to give: the one that means stop, the one that means wait, or neither.

    The same three-way decision the transcript lister makes, in the same order and for the same
    reasons: a walk cut short by the scan cap knows nothing about absence and says so
    (`scan_incomplete`, which is shared vocabulary because the situation is not about recordings,
    down to its having no remedy — the window cannot send the next call further into the
    collection, so what the caller is told is to stop rather than to narrow and retry),
    and otherwise the evidence is `OccurrenceWindow.settled` — shared with the transcript listing
    because the inference is the same one, Microsoft publishing neither a processing status nor a
    latency SLA for either artifact. Only the settled word differs, because "was not transcribed"
    and "was not recorded" are different facts about a meeting.
    """
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
    """The organiser's Entra object id, or None where Graph named nobody.

    Graph sends the organiser as an `identitySet`, and the `@odata.type` on the user inside it is
    not always one the SDK knows — Microsoft's own list-recordings sample sends
    `#Microsoft.Teams.GraphSvc.teamworkUserIdentity` rather than `#microsoft.graph.…`. An unknown
    discriminator deserializes to the base `identity`, which still carries the id, so nothing here
    depends on the subtype.
    """
    organizer = recording.meeting_organizer
    if organizer is None or organizer.user is None:
        return None
    return organizer.user.id


def _content_access(organizer: str | None, caller: str | None) -> str:
    """Which side of Microsoft's organiser-only download rule the signed-in user is on.

    `None` for either id means it cannot be told, which is its own answer: guessing "organiser"
    would promise a download Microsoft refuses, and guessing "participant" would send a caller to
    ask somebody for a file they already have. Ids are compared case-insensitively — an Entra
    object id is a GUID and its casing is not part of its identity.
    """
    if organizer is None or caller is None:
        return "unknown"
    theirs = organizer.casefold() == caller.casefold()
    return "you_are_the_organizer" if theirs else "organizer_only"


def _duration_seconds(recording: CallRecording) -> float | None:
    """How long the recording runs, or None where Graph did not say enough to know.

    Both timestamps are resolved on the same UTC assumption the occurrence window uses, so a
    payload that omitted its `Z` cannot make this subtraction raise. A negative result is not a
    duration — Graph's negative offsets are a property of *content* cue times, not of these two
    fields — so it is reported as unknown rather than as a negative number of seconds.
    """
    began, ended = recording.created_date_time, recording.end_date_time
    if began is None or ended is None:
        return None
    seconds = (as_utc(ended) - as_utc(began)).total_seconds()
    return seconds if seconds >= 0 else None
