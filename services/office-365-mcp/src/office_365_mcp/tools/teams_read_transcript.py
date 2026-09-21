"""`teams_read_transcript` — speaker-attributed, timestamped turns from a Teams meeting transcript.

The handle holds both ids, so one call reaches `/content`. Taking `meeting_uri` instead
re-resolves the join URL, spends a second permission, and answers a 403 meaning either failure.
Declaring `OnlineMeetingTranscript.Read.All` alone lets a tenant withhold `OnlineMeetings.Read`.
That permission is named in `shared/meetings.py` rather than here or in the tool that mints the
handle, because `tests/test_layering.py` rule 4 forbids one tool importing another.

**Speaker attribution degrades rather than fails.** A tenant can forbid names, and this then asks
the same endpoint for the unattributed format; `services/teams-mcp` hardcodes `Accept: text/vtt`
and loses the transcript entirely. The retry is scoped to the `SpeakerAttributionNotAllowed` inner
code: the tenant-wide switch that blocks transcripts outright answers with the same 403, and no
format fixes that one. Both attempts are `graph_step`s inside ONE `graph_errors` for the whole
call. The raw SDK error carries no inner code until a step block translates it, and two
`graph_errors` blocks would count the refused first attempt as a `forbidden` operation on a call
that went on to succeed. The two steps are named apart so the rate of `transcript_unattributed`
shows how often a tenant's setting costs a caller the speaker names. No operation-level series can
show that rate.

**The body goes to a file, and the parse retains only the page.** A transcript is the largest
thing this connector reads: 9.2 MiB of WebVTT measured here held 80,746 turns. Parsing all of it
into a list, filtering that into a second list and then slicing twenty turns out of the result
retained 84.9 MiB of Python objects for an answer of twenty, inside a pod limited to 384 MiB — one
request could fill it. So the response is streamed to a file by `graph_client.download_to_file`,
and the reader below walks that file one cue block at a time, keeping a turn only when it survives
the filters and falls inside the requested window. The same twenty turns then cost 0.15 MiB. The
claim is about what is RETAINED, not about work avoided: the page at offset 11,400, where nothing
can be skipped, parses every turn before it and measures the same 0.15 MiB.

**The parse reads one match past the window, because that is what `next_offset` asks.** Null means
this was the last page, and `offset + len(page)` means there is more. "The window is full" does
not distinguish them, so the loop stops at the first match whose filtered index is
`offset + len(page)` and reports that index. The three filters apply before paging, so `offset`
indexes the filtered sequence and not the transcript.

**The ceiling bounds the download, which never had one.** `MAX_TURNS` bounds the answer; nothing
bounded the fetch. `MAX_TRANSCRIPT_BYTES` is enforced by the helper twice, against the declared
`Content-Length` before a byte is read and against the bytes actually written, and a transcript
over it is refused in this tool's own words. It has to be: `GraphResponseTooLarge` has no branch
in `shared/seam.py`, whose generic tail would tell a caller that Microsoft rejected a bad request,
which is false twice over. The refusal is worded outside the `graph_errors` block, because a
`ToolError` raised inside it would be counted as `status="error"` on `graph_operations_total` —
the label that means this connector is broken — where the escaping `GraphResponseTooLarge` is
counted `too_large`, which is what happened. The size is a PER-REQUEST ceiling, sized against the
pod's `/tmp` — a 64 MiB emptyDir shared by every in-flight request — rather than against the
384 MiB memory limit: the file is node storage and costs the process nothing, but overrunning that
volume evicts the pod, which is worse than the refusal it would replace. Ten MiB each therefore
assumes at most six transcript reads in flight at once, and nothing here enforces that: there is no
semaphore in this service and no request-concurrency cap in its chart. Six is not a bound this
establishes, it is the concurrency at which the volume stops being large enough, and it is written
down so that whoever changes either number sees the other. It is strictly further off than what it
replaces, which reached the memory limit at about two concurrent reads.

**Nothing is cached, and every page still re-downloads the transcript.** `/content` publishes no
ranged read, so the whole body still crosses the wire on every call, exactly as before. The file
is deleted when the block reading it closes, and making one outlive a call is a different change:
Graph re-checks access on every read, so any key would have to name the CALLER as well as the
transcript, or one user's meeting would be answered to another. What changed here is retention.

**The parse runs inside `graph_errors`, which it did not before.** The file exists only inside the
download block, so anything the parse raises now lands as `status="error"` on the operation. Two
things keep that honest. The arguments are validated and the scratch directory is resolved before
the block is entered, so a bad argument still costs no Graph request. And the reader cannot raise:
a block with no cue timing is skipped, undecodable bytes are replaced rather than refused, and a
block is truncated at `_MAX_BLOCK_CHARACTERS` instead of carried whole, because a transcript with
no blank line in it would otherwise grow one block to the size of the file and rebuild in memory
the very thing this removes.

**That cap is on the read, not only on the block, because one line can be the whole file.**
Counting characters between lines bounds how many lines a block carries and nothing else: `for line
in handle` materialises a line before anything can measure it, and WebVTT normally writes a cue's
payload on a single line, so the shape that actually threatens this is a cue with no newline in it.
On an 8 MiB body holding one such cue — under the ceiling, so not refused — a reader guarding only
between lines peaked at 125.1 MiB, because `from_block` and `_spoken` copy that one string five
times over; reading through `handle.readline(_MAX_BLOCK_CHARACTERS)` peaked at 15.9 MiB and parsed
the cue after it unchanged. Graph does not emit such a body, so this is a bound being made true
rather than a bug being fixed: over seventeen adversarial inputs and the 80,746-turn transcript the
capped read answered exactly what reading whole lines answered. What the cap does when it fires is
silent and semantic — the turn still comes back, speaker and timings intact and its words cut
mid-word, and nothing in the answer says so.

**A block ends at a line of nothing but spaces and tabs, which is narrower than `str.strip()`.**
That is the rule the whole-text `\n[ \t]*\n` split this replaces encoded, and the difference is
real: over nineteen adversarial inputs read in both formats — CRLF, a lone CR, a BOM at the start
and a BOM midway, space, tab, form-feed and vertical-tab separators, runs of three and four
newlines, no trailing newline, two cues with no blank line between them, invalid UTF-8, a no-break
space, U+2028, an empty file, a header alone — this reader answered exactly what the old split
answered in all thirty-eight, and a `str.strip()` reader answered differently in four, splitting a
block the old one kept whole. `TestTheSeparatorAndTheDecodeThatWereMeasured` holds the four of
those inputs that a `str.strip()` reader loses, and the BOM that `encoding="utf-8-sig"` eats, so
the rule is pinned rather than only attested here. `TranscriptTurn.from_block` then drops the
blank lines, takes the FIRST line that matches `_CUE_TIMING` and joins everything after it as the
payload, which is why a cue identifier line is harmless and why a block holding two cues yields one
turn. Opening the file
with `encoding="utf-8-sig"`, `errors="replace"` and universal newlines reproduces the decode this
used to do over the whole body at once, incrementally — a character split across two hand-decoded
chunks would otherwise become a replacement character and silently rename a speaker.
"""

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

MAX_TRANSCRIPT_BYTES = 10 * 1024 * 1024

_DESCRIPTION = f"""\
Returns one Teams meeting transcript's spoken turns, timestamped and speaker-attributed, from \
the `uri` teams_list_meeting_transcripts reports, for what was said or decided. \
teams_read_message is the other reader, and it takes a different handle. `meeting_uri` is not \
valid for either tool.

Notes:
- If `speaker_attribution` comes back false, every `speaker` is null and a `speaker` filter \
matches nothing.
- Pass `from_seconds` before `to_seconds`. A window that runs backwards matches nothing.
- Transcripts above {MAX_TRANSCRIPT_BYTES // (1024 * 1024)} MB are refused rather than read in \
part. No argument makes the call smaller.
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

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this transcript. The handle is well formed. Most likely the "
    + "meeting expires after about 60 days for a one-off. Transcripts age out with it. Call "
    + "teams_list_meeting_transcripts again to see what remains. If not listed there, retrying "
    + "will not "
    + "help."
)


def _too_large(refusal: GraphResponseTooLarge) -> str:
    """The refusal a caller reads, in this tool's words rather than the seam's generic advice.

    `size` is set when the bytes written passed the ceiling and `declared` when `Content-Length`
    did, and exactly one of them is, so neither is interpolated on its own.
    """
    counted = refusal.size if refusal.size is not None else refusal.declared
    measured = "of a size Microsoft did not declare" if counted is None else f"{counted} bytes"
    return (
        f"This transcript is {measured}, and this connector reads at most "
        + f"{MAX_TRANSCRIPT_BYTES}. No turns were read. Nothing about the request is wrong and no "
        + "argument makes it smaller: from_seconds, to_seconds and speaker narrow the answer, not "
        + "the call, and Microsoft publishes no ranged read of a transcript, so every call for "
        + "any part of it fetches the whole. Report that this meeting's transcript is too long to "
        + "read here, never that the meeting was silent or that no transcript exists. "
        + "teams_list_meeting_transcripts still lists it, and the user can open the meeting in "
        + "Teams and read or download the transcript there."
    )


class TranscriptTurn(BaseModel):
    speaker: str | None = Field(
        description=(
            "Who spoke, or null if the transcript has no speaker attribution or Microsoft did "
            "not name this turn."
        )
    )
    start_seconds: float = Field(
        description=(
            "Turn start in seconds from transcription start, not wall-clock time and not an "
            "offset from meeting start. This value can be negative. Add it to the `started_at` "
            "value that teams_list_meeting_transcripts reported for this transcript, to get an "
            "absolute time."
        )
    )
    end_seconds: float = Field(description="Turn end, same scale as `start_seconds`.")
    text: str = Field(description="Spoken words, with cue markup stripped.")

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
    meeting_id: str = Field(description="Meeting Graph id.")
    transcript_id: str = Field(description="Transcript Graph id.")
    speaker_attribution: bool = Field(
        description=(
            "True if speakers are named, false if the tenant disabled speaker names — every "
            "`speaker` is null when false. Do not infer who spoke from a turn's content."
        )
    )
    turns: list[TranscriptTurn] = Field(
        description=(
            "Matching turns, or all turns if no filter was passed. Empty means nothing matched, "
            "not that the meeting was silent."
        )
    )
    next_offset: int | None = Field(
        description=(
            "Offset for the next page of matching turns, or null if this is the last page. Pass "
            "it back as `offset`, with the same filters, to continue."
        )
    )


@dataclass(frozen=True, slots=True)
class _Window:
    """What the caller asked for: the three filters, and the slice of what survives them."""

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
    """The page, parsed off a file that exists only inside the download block that wrote it.

    `RequestInformation` is consumed by the send, so the fallback attempt builds its own rather
    than reusing the refused one — and it has to, because the two carry different `Accept` values.
    """
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
    """A `HeadersCollection` that asks for `media_type`, built per request rather than shared.

    The generated builder adds its own `Accept` with `try_add`, which does not overwrite, so this
    one is what goes on the wire.

    It also refuses a content coding. The ceiling is enforced against `Content-Length` before any
    body is read, and under `gzip` that header counts compressed bytes rather than the transcript
    the ceiling is about — so the guard would measure one quantity and claim another. A transcript
    is text and compresses well, so this costs real bandwidth; the alternative is a bound that
    under-fires by whatever the coding happened to save.
    """
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
    """The window's turns, and the filtered offset of the next match past it when one exists.

    One forward pass over the file. Everything that does not match, and everything that matches
    before `offset`, is counted and dropped; only the page itself and the one match that proves
    `next_offset` are ever held.
    """
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
    """Time by overlap, both bounds inclusive; speaker by case-insensitive substring."""
    return (
        (window.from_seconds is None or turn.end_seconds >= window.from_seconds)
        and (window.to_seconds is None or turn.start_seconds <= window.to_seconds)
        and (wanted is None or (turn.speaker is not None and wanted in turn.speaker.casefold()))
    )


def _blocks(path: Path) -> Iterator[str]:
    """Cue blocks, one at a time, from a file this never holds more than one block of.

    The size handed to `readline` is what bounds a block whose lines never end; `held` bounds one
    made of many lines. Both are needed, and neither alone is the cap the module docstring claims.
    """
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
                    "Turns to skip, starting at 0. Pass the previous response's `next_offset` to "
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
                    f"Turns to return, at most {MAX_TURNS}. This tool fetches the whole "
                    "transcript regardless, so a wide `limit` costs less than paging."
                ),
            ),
        ] = 200,
        from_seconds: Annotated[
            float | None,
            Field(
                description=(
                    "Only turns that overlap at or after this moment, in seconds from "
                    "transcription start. This bound is inclusive. A negative value is legal."
                )
            ),
        ] = None,
        to_seconds: Annotated[
            float | None,
            Field(
                description=(
                    "Only turns that overlap at or before this moment, in the same units as "
                    "`from_seconds`. This bound is inclusive. Pair it with `from_seconds` to "
                    "read one stretch."
                )
            ),
        ] = None,
        speaker: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only turns whose speaker name contains this substring, case-insensitive. "
                    "Omit this parameter to read every speaker. A blank value is invalid."
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
