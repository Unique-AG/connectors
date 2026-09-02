"""`teams_read_transcript` — speaker-attributed, timestamped turns from a Teams meeting transcript.

The handle holds both ids, so one call reaches `/content`. Taking `meeting_uri` instead
re-resolves the join URL, spends a second permission, and answers a 403 meaning either failure.
Declaring `OnlineMeetingTranscript.Read.All` alone lets a tenant withhold `OnlineMeetings.Read`.

Speaker attribution degrades rather than fails: a tenant can forbid names and the call then asks
for the unattributed format. `services/teams-mcp` hardcodes `Accept: text/vtt` and has this gap.
"""

import html
import re
from collections.abc import Mapping
from typing import Annotated, Self

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphForbidden, graph_errors, graph_step
from office_365_mcp.shared.handles import TranscriptHandle, transcript_handle
from office_365_mcp.shared.meetings import TRANSCRIPT_PERMISSION
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_read_transcript"

# Counted apart so the rate of `transcript_unattributed` shows how often a tenant's setting costs a
# caller the speaker names. No operation-level series can show that rate.
STEP_ATTRIBUTED = "transcript_attributed"
STEP_UNATTRIBUTED = "transcript_unattributed"

# Admin-consented and independent from the recording permissions. The name lives in
# `shared/meetings.py`: `tests/test_layering.py` rule 4 forbids importing
# teams_list_meeting_transcripts.
GRAPH_PERMISSIONS: tuple[str, ...] = (TRANSCRIPT_PERMISSION,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///transcripts/MSpiYTMyMWUwZC03OWVlLTQ3OGQtOGUyOC04NWExOTUwN2Y0NTYqMCoq"
    + "/MSMjMCMjSYNTHETIC0002"
}

# It bounds the context size. The whole transcript is fetched either way.
MAX_TURNS = 500

_DESCRIPTION = """\
Return a Teams meeting transcript's spoken turns, timestamped and speaker-attributed, from the \
`uri` teams_list_meeting_transcripts reports. Call it for what was actually said or decided. \
teams_read_message is the other reader and takes a different handle, and a `meeting_uri` is not \
one. \
When `speaker_attribution` is false, every `speaker` is null, and a `speaker` filter matches \
nothing. Before you report that somebody did not speak, read that flag. Returns turns with \
speaker, seconds, and text.\
"""

_NOT_A_TRANSCRIPT_HANDLE = (
    "teams_read_transcript takes teams:///transcripts/{meeting_id}/{transcript_id} from "
    + "teams_list_meeting_transcripts. This is not that shape. Call "
    + "teams_list_meeting_transcripts and use its "
    + "`uri`, not the meeting's `meeting_uri` or a Teams message handle. Retrying will fail "
    + "identically."
)

_INVERTED_TIME_WINDOW = (
    "from_seconds is later than to_seconds — no turn matches both. Swap them or drop one. "
    + "Both are offsets from transcription start, counting up."
)

_BLANK_SPEAKER = (
    "blank speaker filter is not treated as no filter: omit it entirely to read every turn, or "
    + "pass any part of the display name (case-insensitive, matches anywhere)."
)

# The default 404 advice, to check the id came from a tool response verbatim, is wrong here because
# the handle did.
GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this transcript. The handle is well formed. Most likely the "
    + "meeting expires after about 60 days for a one-off. Transcripts age out with it. Call "
    + "teams_list_meeting_transcripts again to see what remains. If not listed there, retrying "
    + "will not "
    + "help."
)


class TranscriptTurn(BaseModel):
    speaker: str | None = Field(
        description=(
            "Who spoke. Null if transcript has no speaker attribution or Microsoft did not name "
            "this turn."
        )
    )
    start_seconds: float = Field(
        description=(
            "Turn start in seconds from transcription start — not wall-clock, and not an offset "
            "from meeting start. Can be negative. Add it to the transcript's `started_at` for an "
            "absolute time."
        )
    )
    end_seconds: float = Field(description="Turn end, same scale.")
    text: str = Field(description="Spoken words without cue markup.")

    @classmethod
    def from_block(cls, block: str, *, attributed: bool) -> Self | None:
        lines = [line for line in block.split("\n") if line.strip()]
        timing = next(
            (
                (index, match)
                for index, line in enumerate(lines)
                if (match := _CUE_TIMING.match(line))
            ),
            None,
        )
        if timing is None:
            return None
        index, match = timing
        speaker, said = _spoken("\n".join(lines[index + 1 :]), attributed=attributed)
        if not said:
            return None
        return cls(
            speaker=speaker,
            start_seconds=_seconds(match.group("start")),
            end_seconds=_seconds(match.group("end")),
            text=said,
        )


class Transcript(BaseModel):
    uri: str = Field(description="The handle used to read this, echoed back.")
    meeting_id: str = Field(description="Meeting id.")
    transcript_id: str = Field(description="Transcript Graph id.")
    speaker_attribution: bool = Field(
        description=(
            "True if speakers named. False if tenant turned speaker names off. All `speaker` "
            "values null when false. Do not guess who spoke from content."
        )
    )
    turns: list[TranscriptTurn] = Field(
        description=(
            "Matching turns (or all turns if no filter). Empty means none matched, not that the "
            "meeting was silent."
        )
    )
    next_offset: int | None = Field(
        description=(
            "Offset for next page of matching turns, or null if this is the last page. Pass the "
            "same filters. A page with `next_offset` set is not the whole meeting."
        )
    )


async def teams_read_transcript(
    client: GraphServiceClient,
    *,
    handle: TranscriptHandle,
    offset: int,
    limit: int,
    from_seconds: float | None = None,
    to_seconds: float | None = None,
    speaker: str | None = None,
) -> Transcript:
    """Matching turns from `offset`. One Graph request, or two when attribution is refused."""
    assert 1 <= limit <= MAX_TURNS, f"limit must be within 1..{MAX_TURNS}, got {limit}"
    assert offset >= 0, f"offset must not be negative, got {offset}"
    assert from_seconds is None or to_seconds is None or from_seconds <= to_seconds, (
        f"from_seconds must not be after to_seconds, got {from_seconds} and {to_seconds}"
    )

    # REVIEW: every page refetches and reparses the whole transcript — `/content` has no ranged
    # contract. Any cache key must include the caller: Graph checks access on every read.
    content, attributed = await _content(client, handle)

    turns = _matching(
        _turns(content, attributed=attributed),
        from_seconds=from_seconds,
        to_seconds=to_seconds,
        speaker=speaker,
    )
    page = turns[offset : offset + limit]
    more_to_come = offset + len(page) < len(turns)
    return Transcript(
        uri=handle.uri,
        meeting_id=handle.meeting_id,
        transcript_id=handle.transcript_id,
        speaker_attribution=attributed,
        turns=page,
        next_offset=offset + len(page) if more_to_come else None,
    )


def _matching(
    turns: list[TranscriptTurn],
    *,
    from_seconds: float | None,
    to_seconds: float | None,
    speaker: str | None,
) -> list[TranscriptTurn]:
    wanted = speaker.strip().casefold() if speaker is not None else None
    return [
        turn
        for turn in turns
        if (from_seconds is None or turn.end_seconds >= from_seconds)
        and (to_seconds is None or turn.start_seconds <= to_seconds)
        and (wanted is None or (turn.speaker is not None and wanted in turn.speaker.casefold()))
    ]


# Graph inner code: the tenant permits transcripts but forbids speaker names.
_SPEAKER_ATTRIBUTION_REFUSED = "SpeakerAttributionNotAllowed"

# VTT is the only format with `<v Speaker>` tags. Both are selected by header, never by `$format`.
_ATTRIBUTED_FORMAT = "text/vtt"
_UNATTRIBUTED_FORMAT = "application/vnd.microsoft.graph.transcript+text"


async def _content(client: GraphServiceClient, handle: TranscriptHandle) -> tuple[bytes, bool]:
    """Transcript bytes and whether they carry speaker names.

    Retries once, only for the `SpeakerAttributionNotAllowed` inner code: the tenant-wide switch
    that blocks transcripts answers with the same 403, and no retry fixes that one. Each attempt is
    its own `graph_step` inside one `graph_errors` for the whole call — the raw SDK error carries no
    inner code until a step block translates it, and two `graph_errors` blocks count the refused
    first attempt as a `forbidden` operation on a call that went on to succeed.
    """
    endpoint = (
        client.me.online_meetings.by_online_meeting_id(handle.meeting_id)
        .transcripts.by_call_transcript_id(handle.transcript_id)
        .content
    )
    with graph_errors(TOOL_NAME):
        try:
            with graph_step(STEP_ATTRIBUTED):
                attributed = await endpoint.get(
                    request_configuration=RequestConfiguration(
                        headers=_accepting(_ATTRIBUTED_FORMAT)
                    )
                )
        except GraphForbidden as refusal:
            if refusal.inner_code != _SPEAKER_ATTRIBUTION_REFUSED:
                raise
            with graph_step(STEP_UNATTRIBUTED):
                unattributed = await endpoint.get(
                    request_configuration=RequestConfiguration(
                        headers=_accepting(_UNATTRIBUTED_FORMAT)
                    )
                )
            return (unattributed or b"", False)
        return (attributed or b"", True)


def _accepting(media_type: str) -> HeadersCollection:
    """A `HeadersCollection` that asks for `media_type`, built per request rather than shared."""
    headers = HeadersCollection()
    headers.add("Accept", media_type)
    return headers


# WebVTT cue timing line. The hours are optional, and a leading sign marks a negative offset.
_TIMESTAMP = r"-?(?:\d+:)?\d{1,2}:\d{1,2}[.,]\d{1,3}"
_CUE_TIMING = re.compile(rf"^(?P<start>{_TIMESTAMP})\s*-->\s*(?P<end>{_TIMESTAMP})")

# Voice span: `<v Speaker>text</v>`. A class suffix is allowed, such as `<v.loud Name>`.
_VOICE = re.compile(r"<v(?:\.[^\s>]+)?\s+(?P<speaker>[^>]*)>(?P<said>.*?)(?:</v>|\Z)", re.DOTALL)

# Other cue tags: `<i>`, `<c>`, `<00:00:01.000>` timestamps, `<lang>`.
_MARKUP = re.compile(r"<[^>]*>")

_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def _turns(content: bytes, *, attributed: bool) -> list[TranscriptTurn]:
    text = content.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    turns: list[TranscriptTurn] = []
    for block in _BLANK_LINE.split(text):
        turn = TranscriptTurn.from_block(block, attributed=attributed)
        if turn is not None:
            turns.append(turn)
    return turns


def _spoken(payload: str, *, attributed: bool) -> tuple[str | None, str]:
    """Payload as (speaker, words). The speaker is read before the markup is stripped."""
    voice = _VOICE.search(payload) if attributed else None
    speaker = html.unescape(voice.group("speaker")).strip() if voice is not None else None
    said = voice.group("said") if voice is not None else payload
    words = html.unescape(_MARKUP.sub("", said)).replace("\xa0", " ")
    return (speaker or None, " ".join(words.split()))


def _seconds(timestamp: str) -> float:
    """WebVTT timestamp as seconds, sign kept. Both HH:MM:SS.mmm and MM:SS.mmm are accepted."""
    negative = timestamp.startswith("-")
    parts = timestamp.lstrip("-").replace(",", ".").split(":")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return -total if negative else total


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Read a Meeting Transcript",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def read_meeting_transcript(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The transcript from teams_list_meeting_transcripts: "
                    "teams:///transcripts/{meeting_id}/{transcript_id}. A `meeting_uri` is not "
                    "readable here."
                ),
            ),
        ],
        offset: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "Turns to skip. Start at 0. Pass the previous response's `next_offset` to "
                    "continue."
                ),
            ),
        ] = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_TURNS,
                description=(
                    f"Turns to return (default 200, max {MAX_TURNS}). Whole transcript fetches "
                    "either way. A wider limit is cheaper than paging."
                ),
            ),
        ] = 200,
        from_seconds: Annotated[
            float | None,
            Field(
                description=(
                    "Only turns from this moment (seconds from transcription start). Inclusive, "
                    "matched by overlap. Negative is legal. Narrows answer, not call."
                )
            ),
        ] = None,
        to_seconds: Annotated[
            float | None,
            Field(
                description=(
                    "Only turns until this moment. Inclusive, matched by overlap. Pair with "
                    "`from_seconds` to read one stretch."
                )
            ),
        ] = None,
        speaker: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only turns whose speaker's name contains this (substring, case-insensitive). "
                    "**If `speaker_attribution` is false this matches NOTHING** — every turn's "
                    "`speaker` is null. Omit to read all speakers."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> Transcript:
        handle = transcript_handle(uri)
        if handle is None:
            raise ToolError(_NOT_A_TRANSCRIPT_HANDLE)
        # The schema cannot carry either rule. Without these checks, both look like a silent
        # meeting.
        if from_seconds is not None and to_seconds is not None and from_seconds > to_seconds:
            raise ToolError(_INVERTED_TIME_WINDOW)
        if speaker is not None and not speaker.strip():
            raise ToolError(_BLANK_SPEAKER)
        return await teams_read_transcript(
            client,
            handle=handle,
            offset=offset,
            limit=limit,
            from_seconds=from_seconds,
            to_seconds=to_seconds,
            speaker=speaker,
        )
