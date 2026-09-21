"""One page of a Teams meeting transcript, read off a streamed file rather than held whole."""

import html
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir
from typing import Annotated, Self

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.headers_collection import HeadersCollection
from kiota_abstractions.request_information import RequestInformation
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import (
    GraphForbidden,
    GraphResponseTooLarge,
    download_to_file,
    graph_errors,
    graph_step,
)
from office_365_mcp.shared.handles import TranscriptHandle, transcript_handle
from office_365_mcp.shared.meetings import TRANSCRIPT_PERMISSION
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_read_transcript"

STEP_ATTRIBUTED = "transcript_attributed"
STEP_UNATTRIBUTED = "transcript_unattributed"

GRAPH_PERMISSIONS: tuple[str, ...] = (TRANSCRIPT_PERMISSION,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///transcripts/MSpiYTMyMWUwZC03OWVlLTQ3OGQtOGUyOC04NWExOTUwN2Y0NTYqMCoq"
    + "/MSMjMCMjSYNTHETIC0002"
}

MAX_TURNS = 500

MAX_TRANSCRIPT_BYTES = 100 * 1024 * 1024

_DESCRIPTION = f"""\
Returns the spoken turns of one Teams meeting transcript. Use this tool to read what a \
meeting said or decided. Each turn has a start time and an end time in seconds. Each turn can \
have a speaker name. Use the `uri` that teams_list_meeting_transcripts reports. \
teams_read_message is the other reader, and it takes a different handle. `meeting_uri` is not \
valid for either tool.

Notes:
- If `speaker_attribution` is false, every `speaker` is null. A `speaker` filter then matches \
nothing.
- `from_seconds` must not be later than `to_seconds`. If `from_seconds` is later than \
`to_seconds`, this tool refuses the call.
- If a transcript is larger than {MAX_TRANSCRIPT_BYTES // (1024 * 1024)} MB, this tool refuses \
it. No argument makes the call smaller.
"""

_NOT_A_TRANSCRIPT_HANDLE = (
    "teams_read_transcript takes the handle teams:///transcripts/{meeting_id}/{transcript_id}. "
    + "teams_list_meeting_transcripts reports that handle. This value has a different shape. "
    + "Call teams_list_meeting_transcripts and use its `uri`. Do not use the meeting "
    + "`meeting_uri`, and do not use a Teams message handle. A retry will fail identically."
)

_INVERTED_TIME_WINDOW = (
    "from_seconds is later than to_seconds. No turn matches both bounds. Swap the two values, "
    + "or drop one value. Both values are offsets in seconds from transcription start, and both "
    + "values increase with time."
)

_BLANK_SPEAKER = (
    "A blank speaker filter is not the same as no filter. To read every turn, omit the speaker "
    + "parameter. To filter, give any part of the speaker name. The match is case-insensitive, "
    + "and it matches anywhere in the name."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this transcript. The handle is well formed. A one-off "
    + "meeting expires after about 60 days, and its transcripts expire with it. Call "
    + "teams_list_meeting_transcripts again to see what remains. If the transcript is not in "
    + "that list, a retry will not help."
)


def _too_large(refusal: GraphResponseTooLarge) -> str:
    counted = refusal.size if refusal.size is not None else refusal.declared
    measured = (
        "Microsoft did not declare the size of this transcript."
        if counted is None
        else f"This transcript is {counted} bytes."
    )
    return (
        f"{measured} This connector reads at most {MAX_TRANSCRIPT_BYTES} bytes. This tool read "
        + "no turns. Nothing about the request is wrong, and no argument makes it smaller. "
        + "from_seconds, to_seconds and speaker narrow the answer, but they do not narrow the "
        + "call. Microsoft publishes no ranged read of a transcript. Every call for any part of "
        + "a transcript fetches the whole transcript. Report that this transcript is too long to "
        + "read here. Do not report that the meeting was silent. Do not report that no "
        + "transcript exists. teams_list_meeting_transcripts still lists this transcript. The "
        + "user can open the meeting in Teams, and read or download the transcript there."
    )


class TranscriptTurn(BaseModel):
    speaker: str | None = Field(
        description=(
            "This value names who spoke. If the transcript has no speaker attribution, this "
            "value is null. If Microsoft did not name this turn, this value is null."
        )
    )
    start_seconds: float = Field(
        description=(
            "This value is the turn start. The unit is seconds from transcription start. This "
            "value is not wall-clock time, and it is not an offset from meeting start. This "
            "value can be negative. To get an absolute time, add this value to the `started_at` "
            "value that teams_list_meeting_transcripts reported for this transcript."
        )
    )
    end_seconds: float = Field(
        description="This value is the turn end. The unit is the unit of `start_seconds`."
    )
    text: str = Field(
        description="This value holds the spoken words. This tool removes the cue markup."
    )

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
    uri: str = Field(description="This tool echoes back the handle that it read.")
    meeting_id: str = Field(description="This value is the meeting Graph id.")
    transcript_id: str = Field(description="This value is the transcript Graph id.")
    speaker_attribution: bool = Field(
        description=(
            "If this value is true, the turns name the speakers. If this value is false, the "
            "tenant disabled speaker names, and every `speaker` is null. Do not infer who spoke "
            "from the content of a turn."
        )
    )
    turns: list[TranscriptTurn] = Field(
        description=(
            "This list holds the turns that match the filters. If the caller gives no filter, "
            "this list holds every turn. An empty list means that nothing matched. An empty "
            "list does not mean that the meeting was silent."
        )
    )
    next_offset: int | None = Field(
        description=(
            "The offset of the next page of matching turns. If this page is the last page, this "
            "value is null. To continue, pass this value back as `offset` with the same filters."
        )
    )


@dataclass(frozen=True, slots=True)
class _Window:
    offset: int
    limit: int
    from_seconds: float | None
    to_seconds: float | None
    speaker: str | None


async def teams_read_transcript(
    client: GraphServiceClient,
    transport: httpx.AsyncClient,
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

    window = _Window(
        offset=offset,
        limit=limit,
        from_seconds=from_seconds,
        to_seconds=to_seconds,
        speaker=speaker,
    )
    scratch = Path(gettempdir())
    try:
        return await _read(client, transport, handle, scratch=scratch, window=window)
    except GraphResponseTooLarge as refusal:
        refused = _too_large(refusal)
    raise ToolError(refused)


async def _read(
    client: GraphServiceClient,
    transport: httpx.AsyncClient,
    handle: TranscriptHandle,
    *,
    scratch: Path,
    window: _Window,
) -> Transcript:
    """The page, parsed off a file that exists only inside the download block that wrote it."""
    endpoint = (
        client.me.online_meetings.by_online_meeting_id(handle.meeting_id)
        .transcripts.by_call_transcript_id(handle.transcript_id)
        .content
    )

    def asking(media_type: str) -> RequestInformation:
        return endpoint.to_get_request_information(
            RequestConfiguration[QueryParameters](headers=_accepting(media_type))
        )

    with graph_errors(TOOL_NAME):
        try:
            with graph_step(STEP_ATTRIBUTED):
                async with download_to_file(
                    client,
                    transport,
                    asking(_ATTRIBUTED_FORMAT),
                    directory=scratch,
                    max_bytes=MAX_TRANSCRIPT_BYTES,
                ) as downloaded:
                    return _paged(downloaded.path, handle=handle, attributed=True, window=window)
        except GraphForbidden as refusal:
            if refusal.inner_code != _SPEAKER_ATTRIBUTION_REFUSED:
                raise
        with graph_step(STEP_UNATTRIBUTED):
            async with download_to_file(
                client,
                transport,
                asking(_UNATTRIBUTED_FORMAT),
                directory=scratch,
                max_bytes=MAX_TRANSCRIPT_BYTES,
            ) as downloaded:
                return _paged(downloaded.path, handle=handle, attributed=False, window=window)


def _accepting(media_type: str) -> HeadersCollection:
    """A `HeadersCollection` that asks for `media_type`, built per request rather than shared."""
    headers = HeadersCollection()
    headers.add("Accept", media_type)
    headers.add(*_NO_CONTENT_CODING)
    return headers


def _paged(
    path: Path, *, handle: TranscriptHandle, attributed: bool, window: _Window
) -> Transcript:
    turns, next_offset = _page(path, attributed=attributed, window=window)
    return Transcript(
        uri=handle.uri,
        meeting_id=handle.meeting_id,
        transcript_id=handle.transcript_id,
        speaker_attribution=attributed,
        turns=turns,
        next_offset=next_offset,
    )


def _page(
    path: Path, *, attributed: bool, window: _Window
) -> tuple[list[TranscriptTurn], int | None]:
    """The window's turns, and the filtered offset of the next match past it when one exists."""
    wanted = window.speaker.strip().casefold() if window.speaker is not None else None
    page: list[TranscriptTurn] = []
    matched = 0
    for block in _blocks(path):
        turn = TranscriptTurn.from_block(block, attributed=attributed)
        if turn is None or not _matching(turn, window=window, wanted=wanted):
            continue
        if matched >= window.offset:
            if len(page) == window.limit:
                return (page, matched)
            page.append(turn)
        matched += 1
    return (page, None)


def _matching(turn: TranscriptTurn, *, window: _Window, wanted: str | None) -> bool:
    """Time matches by overlap, both bounds inclusive. Speaker matches by substring, folded."""
    return (
        (window.from_seconds is None or turn.end_seconds >= window.from_seconds)
        and (window.to_seconds is None or turn.start_seconds <= window.to_seconds)
        and (wanted is None or (turn.speaker is not None and wanted in turn.speaker.casefold()))
    )


def _blocks(path: Path) -> Iterator[str]:
    """Cue blocks, one at a time, from a file this never holds more than one block of."""
    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        block: list[str] = []
        held = 0
        while (line := handle.readline(_MAX_BLOCK_CHARACTERS)) != "":
            if line.strip(" \t\n") == "":
                yield "".join(block)
                block = []
                held = 0
            elif held < _MAX_BLOCK_CHARACTERS:
                block.append(line)
                held += len(line)
        yield "".join(block)


_SPEAKER_ATTRIBUTION_REFUSED = "SpeakerAttributionNotAllowed"

_ATTRIBUTED_FORMAT = "text/vtt"
_UNATTRIBUTED_FORMAT = "application/vnd.microsoft.graph.transcript+text"

_NO_CONTENT_CODING = ("Accept-Encoding", "identity")

_TIMESTAMP = r"-?(?:\d+:)?\d{1,2}:\d{1,2}[.,]\d{1,3}"
_CUE_TIMING = re.compile(rf"^(?P<start>{_TIMESTAMP})\s*-->\s*(?P<end>{_TIMESTAMP})")

_VOICE = re.compile(r"<v(?:\.[^\s>]+)?\s+(?P<speaker>[^>]*)>(?P<said>.*?)(?:</v>|\Z)", re.DOTALL)

_MARKUP = re.compile(r"<[^>]*>")

_MAX_BLOCK_CHARACTERS = 1024 * 1024


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
                    "The transcript handle from teams_list_meeting_transcripts: "
                    "`teams:///transcripts/{meeting_id}/{transcript_id}`. A `meeting_uri` is not "
                    "valid here."
                ),
            ),
        ],
        offset: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "This value is the number of turns to skip. The first turn is 0. To "
                    "continue, pass the `next_offset` value of the previous response."
                ),
            ),
        ] = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_TURNS,
                description=(
                    "This value is the number of turns to return. The maximum is "
                    f"{MAX_TURNS}. This tool fetches the whole transcript for every call. One "
                    "wide `limit` costs less than several pages."
                ),
            ),
        ] = 200,
        from_seconds: Annotated[
            float | None,
            Field(
                description=(
                    "This tool returns only the turns that overlap at or after this moment. The "
                    "unit is seconds from transcription start. This bound is inclusive. A "
                    "negative value is valid."
                )
            ),
        ] = None,
        to_seconds: Annotated[
            float | None,
            Field(
                description=(
                    "This tool returns only the turns that overlap at or before this moment. "
                    "The unit is the same as the unit of `from_seconds`. This bound is "
                    "inclusive. To read one window, give this value and `from_seconds` "
                    "together."
                )
            ),
        ] = None,
        speaker: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "This tool returns only the turns whose speaker name contains this "
                    "substring. The match is case-insensitive. To read every turn, omit "
                    "this parameter. A blank value is invalid."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> Transcript:
        handle = transcript_handle(uri)
        if handle is None:
            raise ToolError(_NOT_A_TRANSCRIPT_HANDLE)
        if from_seconds is not None and to_seconds is not None and from_seconds > to_seconds:
            raise ToolError(_INVERTED_TIME_WINDOW)
        if speaker is not None and not speaker.strip():
            raise ToolError(_BLANK_SPEAKER)
        return await teams_read_transcript(
            client,
            transport,
            handle=handle,
            offset=offset,
            limit=limit,
            from_seconds=from_seconds,
            to_seconds=to_seconds,
            speaker=speaker,
        )
