"""`read_transcript` — speaker-attributed, timestamped turns from a Teams meeting transcript.

The handle holds the meeting id and the transcript id, so one call reaches `/content`. A reader
that took the meeting's `meeting_uri` instead would resolve the join URL that
`list_meeting_transcripts` already resolved, spend a second permission, and answer a 403 that could
mean either failure. This tool declares `OnlineMeetingTranscript.Read.All` alone, so a tenant can
withhold `OnlineMeetings.Read` and this tool still answers.

Speaker attribution degrades rather than fails: a tenant can forbid speaker names, and the call
then asks for the unattributed format Microsoft documents. `services/teams-mcp` still hardcodes
`Accept: text/vtt` and has this gap. `from_seconds`, `to_seconds`, `speaker` and the paging all
apply after the whole transcript arrives and is parsed, so no argument makes the call cheaper.
Inverted time bounds and a blank speaker filter are rejected at the call, because both would answer
with an empty page.
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

from office_mcp.graph_client import GraphForbidden, graph_errors, graph_step
from office_mcp.shared.handles import TranscriptHandle, transcript_handle
from office_mcp.shared.meetings import TRANSCRIPT_PERMISSION
from office_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "read_transcript"

# The two attempts this tool can make, counted apart. A tenant that will not give speaker names
# refuses the first and answers the second, so the rate of `transcript_unattributed` is how often
# that setting costs a caller the speaker names. No operation-level series can show that rate.
STEP_ATTRIBUTED = "transcript_attributed"
STEP_UNATTRIBUTED = "transcript_unattributed"

# The one permission this tool's one request needs, admin-consented and independent from recording
# permissions. `list_meeting_transcripts` declares it too. The name lives in `shared/meetings.py`,
# because `tests/test_layering.py` rule 4 forbids one tool file from importing another.
GRAPH_PERMISSIONS: tuple[str, ...] = (TRANSCRIPT_PERMISSION,)

# One call that reaches Graph, read by `tools/__init__.py` into the coverage table
# `tests/test_error_mapping.py` refuses every registered tool from. The ids are invented, but the
# shape must be one this tool accepts: an argument it rejects never reaches Graph to be refused.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///transcripts/MSpiYTMyMWUwZC03OWVlLTQ3OGQtOGUyOC04NWExOTUwN2Y0NTYqMCoq"
    + "/MSMjMCMjSYNTHETIC0002"
}

# Max turns per call. It bounds the context size. The whole transcript is fetched either way.
MAX_TURNS = 500

_DESCRIPTION = f"""\
Read the words from a Teams meeting transcript: speaker-attributed, timestamped turns. \
Takes the `uri` from list_meeting_transcripts.

The `uri` shape is teams:///transcripts/{{meeting_id}}/{{transcript_id}}. Only this tool and \
list_meeting_transcripts mint this shape. read_message is a different reader with a different \
handle.

Seconds are offsets from transcription start, not wall-clock times and not offsets from meeting \
start. They can be negative (Microsoft uses that when transcription began after conversation did). \
Add them to the transcript's `started_at` if you need absolute time.

`speaker_attribution` is false when your organisation turned speaker names off. Words and timings \
still arrive; every `speaker` is null. Do not guess who spoke from content. **A `speaker` filter \
matches NOTHING on such a transcript** — every turn's `speaker` is null by construction. When \
filtering yields nothing, read the `speaker_attribution` flag before saying the person did not \
speak.

`from_seconds`, `to_seconds`, `speaker` narrow the answer. The whole transcript fetches either \
way, so these make the answer smaller, not the call cheaper. Time bounds are inclusive and match \
by overlap — a turn already under way at `from_seconds` keeps whole. Speaker matches any part of \
the display name, ignoring case. `next_offset` pages through MATCHING turns, not the meeting.

Paging: each call re-fetches from Microsoft. A wider `limit` (up to {MAX_TURNS}) costs less than \
paging. `next_offset` is null on the last page and set on all others — the same as \
search_messages. A page with `next_offset` set is not the whole meeting.\
"""

_NOT_A_TRANSCRIPT_HANDLE = (
    "read_transcript takes teams:///transcripts/{meeting_id}/{transcript_id} from "
    + "list_meeting_transcripts. This is not that shape. Call list_meeting_transcripts and use its "
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

# A transcript ages out with its meeting rather than being deleted, about 60 days after a one-off.
# Say the meeting "expires", not "expired": the policy makes it unreadable, not a past event.
#
# Read by `tools/__init__.py` into the advice table `GraphAdviceMiddleware` words a 404 from. Public
# for that reason: the default advice ("check the id came from a tool response verbatim") is wrong
# here, because the handle did come from one.
GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this transcript. The handle is well formed. Most likely the "
    + "meeting expires after about 60 days for a one-off; transcripts age out with it. Call "
    + "list_meeting_transcripts again to see what remains. If not listed there, retrying will not "
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
        description="Turn start in seconds from transcription start. Can be negative."
    )
    end_seconds: float = Field(description="Turn end, same scale.")
    text: str = Field(description="Spoken words without cue markup.")

    @classmethod
    def from_block(cls, block: str, *, attributed: bool) -> Self | None:
        """One cue block as a turn, or None when the block is not a cue or holds no words."""
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
            "values null when false."
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
            "same filters."
        )
    )


async def read_transcript(
    client: GraphServiceClient,
    *,
    handle: TranscriptHandle,
    offset: int,
    limit: int,
    from_seconds: float | None = None,
    to_seconds: float | None = None,
    speaker: str | None = None,
) -> Transcript:
    """Matching turns from `offset`, up to `limit`.

    One Graph request, or two when Graph refuses speaker attribution.
    """
    assert 1 <= limit <= MAX_TURNS, f"limit must be within 1..{MAX_TURNS}, got {limit}"
    assert offset >= 0, f"offset must not be negative, got {offset}"
    assert from_seconds is None or to_seconds is None or from_seconds <= to_seconds, (
        f"from_seconds must not be after to_seconds, got {from_seconds} and {to_seconds}"
    )

    # REVIEW: every page refetches and reparses the whole transcript, because `/content` has no
    # ranged contract. Caching the parsed turns would help, but the key must include the caller:
    # the token is the caller's own, and Graph checks that caller's access on every read.
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
    """Turns matching all filters.

    The time test is overlap, both bounds inclusive. The speaker test is a case-insensitive
    substring, and whitespace around the filter is ignored.
    """
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

# VTT is the default and the only format with `<v Speaker>` tags. The unattributed format is a
# fallback for a tenant that forbids names. Both are selected by header, never by `$format`.
_ATTRIBUTED_FORMAT = "text/vtt"
_UNATTRIBUTED_FORMAT = "application/vnd.microsoft.graph.transcript+text"


async def _content(client: GraphServiceClient, handle: TranscriptHandle) -> tuple[bytes, bool]:
    """Transcript bytes and whether they carry speaker names.

    Retries once, only for the `SpeakerAttributionNotAllowed` inner code. The tenant-wide switch
    that blocks transcripts answers with the same `403`, and no retry fixes that one, so retrying it
    would waste a call and report the wrong remedy.

    Each attempt is its own `graph_step` block, inside one `graph_errors` block for the whole tool
    call. The step blocks are what translate: the raw SDK error carries no inner code before
    translation, so the `except` clause below needs an attempt-sized block to have already run.

    The nesting also stops a working tenant looking like a broken one. Two `graph_errors` blocks
    counted the refused first attempt as a `forbidden` operation on a call that went on to succeed,
    so any alert on refusals fired on a healthy tenant. The refusal now counts against
    `transcript_attributed`, and the operation counts as an answer.
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
    """Content as turns. One cue per turn. Skip non-cue blocks. Drop empty turns."""
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
    """Register this tool. The tool borrows `transport` per call."""
    # Built here because this is where `transport` is: the dependency closes over it, and the
    # default below is evaluated when the `def` runs, inside this call. The default holds a name,
    # not a call. A call there is ruff's B008.
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
                    "The transcript from list_meeting_transcripts: "
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
                    "Turns to skip. Start at 0; pass the previous response's `next_offset` to "
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
                    "either way; wider limit is cheaper than paging."
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
        # Reject an inverted time window and a blank speaker. Both return nothing, and nothing
        # reads like a silent meeting. The schema cannot carry either rule.
        if from_seconds is not None and to_seconds is not None and from_seconds > to_seconds:
            raise ToolError(_INVERTED_TIME_WINDOW)
        if speaker is not None and not speaker.strip():
            raise ToolError(_BLANK_SPEAKER)
        return await read_transcript(
            client,
            handle=handle,
            offset=offset,
            limit=limit,
            from_seconds=from_seconds,
            to_seconds=to_seconds,
            speaker=speaker,
        )
