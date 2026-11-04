"""Turns of a Teams transcript, parsed off a streamed file rather than held whole."""

import html
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import httpx
from kiota_abstractions.headers_collection import HeadersCollection
from kiota_abstractions.request_information import RequestInformation
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphForbidden, download_to_file, graph_step

CALL_TRANSCRIPT_PERMISSION = "CallTranscripts.Read.All"

STEP_ATTRIBUTED = "transcript_attributed"
STEP_UNATTRIBUTED = "transcript_unattributed"


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
            "value reported for this transcript."
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


@dataclass(frozen=True, slots=True)
class _Window:
    offset: int
    limit: int
    from_seconds: float | None
    to_seconds: float | None
    speaker: str | None


async def read_turns(
    client: GraphServiceClient,
    transport: httpx.AsyncClient,
    request_for: Callable[[HeadersCollection], RequestInformation],
    *,
    directory: Path,
    max_bytes: int,
    offset: int,
    limit: int,
    from_seconds: float | None,
    to_seconds: float | None,
    speaker: str | None,
) -> tuple[list[TranscriptTurn], int | None, bool]:
    """The page, parsed off a file that exists only inside the download block that wrote it."""
    window = _Window(
        offset=offset,
        limit=limit,
        from_seconds=from_seconds,
        to_seconds=to_seconds,
        speaker=speaker,
    )

    def asking(media_type: str) -> RequestInformation:
        return request_for(_accepting(media_type))

    try:
        with graph_step(STEP_ATTRIBUTED):
            async with download_to_file(
                client,
                transport,
                asking(_ATTRIBUTED_FORMAT),
                directory=directory,
                max_bytes=max_bytes,
            ) as downloaded:
                turns, next_offset = _page(downloaded.path, attributed=True, window=window)
                return (turns, next_offset, True)
    except GraphForbidden as refusal:
        if refusal.inner_code != _SPEAKER_ATTRIBUTION_REFUSED:
            raise
    with graph_step(STEP_UNATTRIBUTED):
        async with download_to_file(
            client,
            transport,
            asking(_UNATTRIBUTED_FORMAT),
            directory=directory,
            max_bytes=max_bytes,
        ) as downloaded:
            turns, next_offset = _page(downloaded.path, attributed=False, window=window)
            return (turns, next_offset, False)


def _accepting(media_type: str) -> HeadersCollection:
    headers = HeadersCollection()
    headers.add("Accept", media_type)
    headers.add(*_NO_CONTENT_CODING)
    return headers


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
