"""`read_transcript` — what was said in a Teams meeting, as speaker-attributed, timestamped turns.

This is the payoff of the whole meeting path and the one surface where a delegated connector can
answer better than a link. Microsoft's own M365 connector reaches a transcript through an opaque URI
obtained from a calendar read and returns whatever that yields; the chain here ends in
`/transcripts/{id}/content`, which Graph answers with WebVTT carrying `<v Speaker>` voice tags and
cue timestamps — who said what, when.

Four things make this tool what it is, and each of them is a decision rather than a detail.

**It reads and it does not resolve.** The handle carries the meeting id and the transcript id, so
this call is one Graph request against `/content`. A reader that took the meeting's `meeting_uri`
instead would repeat the join-URL resolve `list_meeting_transcripts` already did, spend a second
request and a second permission, and give a 403 that could be about either of them. That is why
this tool declares `OnlineMeetingTranscript.Read.All` and nothing else, and why a tenant that
withholds `OnlineMeetings.Read` can still read a transcript it was handed a handle for.

**Speaker attribution degrades instead of failing.** A tenant can permit transcripts and forbid
speaker names; Graph's documented remedy is to ask again for
`application/vnd.microsoft.graph.transcript+text`, which `_content` does exactly once and only for
that inner code. `speaker_attribution: false` then says the words and the timings are all there and
the names are not — the gap `services/teams-mcp` still has, since it hardcodes `Accept: text/vtt`.
The tenant-wide switch that blocks transcripts altogether answers with the same `403` and has no
workaround at all, which is why the retry is keyed on the code and never on the status.

**Filtering makes the answer smaller and never the call cheaper.** `/content` is one stream with no
ranged contract, so every page refetches and reparses the whole transcript; `from_seconds`,
`to_seconds` and `speaker` are applied to the parsed turns. They are applied *before* the page is
cut, and `next_offset` is counted over what they left — the only version of "there is more" a
caller can act on. Paging the meeting while filtering each page would make the offset mean "more of
the meeting" while the turns meant "the ones you asked for", and a caller following `next_offset`
to the end would walk pages that hold nothing.

**Two arguments a schema cannot refuse are refused here.** A `from_seconds` later than
`to_seconds`, and a `speaker` that is nothing but spaces. Each would otherwise be answered with an
empty page, and an empty page is indistinguishable from a meeting in which nobody said anything —
the one failure a model reads as a real answer.

What this file does not own is the handle grammar (`shared/handles.py`, so that the transcript
`list_meeting_transcripts` names is the transcript this reads) and the token and refusal wording
(`shared/seam.py`, so this tool's 403 sounds like every other tool's). Everything else — the name,
the description, the arguments, the answer shape, the request, the parser and every refusal below —
is here.
"""

import html
import re
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_mcp.graph_client import GraphForbidden, graph_client_for, graph_errors
from office_mcp.shared.handles import TranscriptHandle, transcript_handle
from office_mcp.shared.meetings import TRANSCRIPT_PERMISSION
from office_mcp.shared.seam import READ_ONLY, graph_token, graph_tool_errors

TOOL_NAME = "read_transcript"

# The one delegated permission this tool's one request needs. Admin-consented in its own right, and
# separately from every other meeting permission: a tenant can grant transcript access and withhold
# recording access, or the other way round. `list_meeting_transcripts` names this one too, because
# listing reads the same resource — two tools declaring one permission is what the registry's
# deduplication is for, and neither may leave it out. The name itself comes from
# `shared/meetings.py`: rule 4 keeps these two files apart, so a permission both of them declare is
# spelled where neither owns it rather than typed out once each.
GRAPH_PERMISSIONS: tuple[str, ...] = (TRANSCRIPT_PERMISSION,)

_TOKEN: str = graph_token(*GRAPH_PERMISSIONS)

# How many turns one read returns, and the ceiling on `limit`. A turn is one WebVTT cue — a sentence
# or two — so an hour of meeting is some hundreds of them and a 30-hour one (Teams' own limit) is
# tens of thousands. The whole transcript is fetched either way; this bounds what crosses into a
# model's context per call.
MAX_TURNS = 500

_DESCRIPTION = f"""\
Read what was said in a Teams meeting: the transcript as speaker-attributed, timestamped turns. \
Takes the `uri` of a transcript that list_meeting_transcripts returned.

This is the payoff of the whole meeting path, and it returns the words themselves rather than a \
link to them — who spoke, in order, with the offset into the meeting at which they spoke. Quote it \
as you would quote a message: it is what people actually said, verbatim, and Microsoft's \
speech-to-text is not perfect, so an odd word is likelier a mis-transcription than a real one.

`uri` takes a handle this connector produced, in exactly one shape:
  teams:///transcripts/{{meeting_id}}/{{transcript_id}}
Nothing else is readable here, and nothing turns a meeting's name, its date, its chat or its \
`meeting_uri` into one — call list_meeting_transcripts and pass its `uri` verbatim. read_message \
is the reader for a Teams message and takes a different handle; neither tool accepts the other's.

`start_seconds` and `end_seconds` are offsets in seconds from the moment transcription began, not \
wall-clock times and not offsets from the start of the meeting; add them to the transcript's \
`started_at` from list_meeting_transcripts if an absolute time is needed. They can be negative, \
which Microsoft defines as transcription having started after the conversation did.

`speaker_attribution` is false when the organisation has turned speaker names off. The words and \
timings still come back and every `speaker` is null: do not infer who spoke from the content, and \
say the transcript is unattributed if the answer turns on who said something. **A `speaker` filter \
matches nothing at all on such a transcript** — there is no name on any turn for it to match — so \
read an empty answer next to this flag before reporting that the person never spoke, and drop the \
filter to see the turns themselves.

`from_seconds`/`to_seconds` and `speaker` narrow what comes back, and everything else is counted \
over what they left: `next_offset` pages through the MATCHING turns rather than through the \
meeting. The time bounds are inclusive and match by overlap, so a turn already under \
way at `from_seconds` is kept whole instead of being cut at it; `speaker` matches any part of the \
name Teams shows, ignoring case, because a display name is not something to spell from memory. \
Filtering does not make the call cheaper — the whole transcript is fetched and parsed either \
way — it makes the answer smaller.

A long meeting is more turns than fit in one answer. `next_offset` says both that there are more \
and where to continue: it is null on the last page and set on every other, which is the same \
convention search_messages pages by. Each call re-fetches the whole transcript from Microsoft, so \
a wider `limit` (up to {MAX_TURNS}) costs less than paging through it, and a page with \
`next_offset` set must never be summarised as the whole meeting.\
"""

# What this tool says when its `uri` is not one of its own handles. Its own text rather than a
# shared one, because the failure it has to prevent is a caller being sent to the wrong tool: the
# message-handle families and this one are read by different tools under different permissions.
_NOT_A_TRANSCRIPT_HANDLE = (
    "read_transcript takes the `uri` of a transcript that list_meeting_transcripts returned, and "
    + "this is not one. A transcript handle has exactly one shape:\n"
    + "  teams:///transcripts/{meeting_id}/{transcript_id}\n"
    + "with both ids percent-encoded. Call list_meeting_transcripts with a meeting chat's "
    + "`meeting_uri` and pass the `uri` of the transcript you want, verbatim. A `meeting_uri` is "
    + "not a transcript handle — one meeting can have many transcripts — and neither is a Teams "
    + "message handle. Retrying this value will fail identically."
)

_INVERTED_TIME_WINDOW = (
    "read_transcript was given a `from_seconds` later than its `to_seconds`, which selects no part "
    + "of the meeting: no turn can both end after the one and start before the other, so this "
    + "would come back empty and read like a silent meeting. Both are offsets in seconds from the "
    + "moment transcription began, counting upwards, so the earlier moment is the smaller number — "
    + "swap them if they were written the wrong way round, or drop one to leave that end open."
)

_BLANK_SPEAKER = (
    "read_transcript was given a blank `speaker`. A blank filter is not the same as no filter, and "
    + "it is not treated as one: omit `speaker` entirely to read every turn, or pass any part of "
    + "the name Teams shows for the person — matching ignores case and matches anywhere in the "
    + "display name, so `ada` finds `Ada Lovelace`. Note that a transcript whose "
    + "`speaker_attribution` is false carries no names at all, and any `speaker` filter matches "
    + "nothing on it."
)

# Graph's 404 on a well-formed transcript handle. Distinct advice from the message reader's, because
# the causes are different: a transcript is not deleted by a user, it ages out with its meeting.
_TRANSCRIPT_UNREADABLE = (
    "Microsoft 365 would not return this transcript. The handle is well formed, so this is not a "
    + "bad argument. The likeliest cause is age: Microsoft stops serving a meeting's transcripts "
    + "once the meeting expires, about 60 days after a one-off meeting, and it answers that "
    + "identically to a transcript that was removed or that this user may not see. Call "
    + "list_meeting_transcripts for the meeting again to see what it still has; if the transcript "
    + "is no longer listed there, it is out of reach and retrying will not bring it back."
)


class TranscriptTurn(BaseModel):
    speaker: str | None = Field(
        description=(
            "Who spoke, as Teams attributed them. Null when this transcript has no speaker "
            + "attribution at all (see `speaker_attribution`) and null for the occasional turn "
            + "Microsoft attributed to nobody — a null is not an unidentified person."
        )
    )
    start_seconds: float = Field(
        description=(
            "When this turn starts, in seconds from the beginning of transcription — not from the "
            + "start of the meeting, and not a wall-clock time. Add it to the transcript's "
            + "`started_at` for that. It can be NEGATIVE: Microsoft documents negative offsets as "
            + "meaning transcription began while the conversation was already under way."
        )
    )
    end_seconds: float = Field(description="When this turn ends, on the same scale.")
    text: str = Field(description="What was said, with Teams' own cue markup removed.")


class Transcript(BaseModel):
    uri: str = Field(description="The handle this transcript was read by, echoed back.")
    meeting_id: str = Field(description="The meeting this transcript belongs to.")
    transcript_id: str = Field(description="The transcript's Graph id.")
    speaker_attribution: bool = Field(
        description=(
            "True when Microsoft named the speakers, which is the normal case. False when this "
            + "tenant has speaker attribution switched off: the words and the timings are all "
            + "still here and every `speaker` is null. Do not guess who spoke from the content, "
            + "and say so if the answer depends on who said something."
        )
    )
    turns: list[TranscriptTurn] = Field(
        description=(
            "What was said, in order, one turn per utterance Microsoft timestamped — the turns "
            + "matching `from_seconds`, `to_seconds` and `speaker` where any of those was given, "
            + "and every turn of the transcript where none was. Empty means nothing matched what "
            + "was asked for, which is not the same as the meeting having no words in it."
        )
    )
    next_offset: int | None = Field(
        description=(
            "The `offset` that reaches the next matching turns, or null when these are the last of "
            + "them. A value here is what says more turns match than this page holds: pass it back "
            + "as `offset` to continue, and never summarise a page with one set as the whole "
            + "meeting. It counts the turns left after `from_seconds`, `to_seconds` and `speaker` "
            + "were applied, so it indexes what was asked for rather than the meeting — send the "
            + "same filters back with it, since changing one renumbers what it points at."
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
    """The turns of one transcript matching the filters, from `offset`, up to `limit` of them.

    One Graph request, or two where the tenant refuses speaker attribution. Paging is over the
    parsed turns rather than over Graph — `/content` is a single stream with no ranged contract —
    so a later page costs the same fetch again, which is what makes `limit` worth widening rather
    than looping. The filters are the same bargain: the whole transcript is fetched and parsed
    whatever they are, so they make the answer smaller and never the call cheaper.
    """
    assert 1 <= limit <= MAX_TURNS, f"limit must be within 1..{MAX_TURNS}, got {limit}"
    assert offset >= 0, f"offset must not be negative, got {offset}"
    assert from_seconds is None or to_seconds is None or from_seconds <= to_seconds, (
        f"from_seconds must not be after to_seconds, got {from_seconds} and {to_seconds}"
    )

    # TODO: every page refetches and reparses the whole transcript, because `/content` has no
    # ranged contract. Caching the parsed turns per handle is the fix.
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
    """The turns of `turns` that all of the given filters keep, in the order they were said.

    **The time test is overlap, and both bounds are inclusive.** A turn is one utterance of a
    sentence or two, and the moment a caller asks about lands in the middle of one about as often
    as it lands between two — so a turn that straddles a bound is kept whole rather than dropped or
    cut. Comparing a turn's *start* to both bounds instead would silently lose the sentence already
    under way at `from_seconds`, which is exactly the sentence that says what the stretch is about.

    **The speaker test is a case-insensitive substring of the display name.** A model asking about
    a person has a name it read somewhere, not the string Teams stores, and those differ by case,
    by a middle name, by a title or by the parenthesised suffix a tenant appends. An exact match
    would answer "that person said nothing" to a spelling difference.

    A turn Microsoft attributed to nobody never matches a speaker filter: `speaker` is null there,
    and there is nothing to compare. Neither does *any* turn of a transcript from a tenant with
    speaker attribution switched off, where every `speaker` is null by construction — this is not
    refused and not degraded to "everything", because a filter that quietly stopped filtering would
    be worse than an empty answer. `Transcript.speaker_attribution` is the flag that explains that
    answer, and every description over this argument says to read the two together.
    """
    wanted = speaker.casefold() if speaker is not None else None
    return [
        turn
        for turn in turns
        if (from_seconds is None or turn.end_seconds >= from_seconds)
        and (to_seconds is None or turn.start_seconds <= to_seconds)
        and (wanted is None or (turn.speaker is not None and wanted in turn.speaker.casefold()))
    ]


# The inner code Graph sends when a tenant permits transcripts but forbids speaker names. Branched
# on rather than the message, as Microsoft's own documentation instructs.
_SPEAKER_ATTRIBUTION_REFUSED = "SpeakerAttributionNotAllowed"

# The two formats `/content` serves. VTT is the default and the one worth having — it is the only
# one carrying `<v Speaker>` voice tags. The other is the documented fallback for a tenant with
# speaker attribution switched off, and is selectable *only* by this header ("the
# application/vnd.microsoft.graph.transcript+text format is supported only through this header"),
# which is why neither is requested with `$format`.
_ATTRIBUTED_FORMAT = "text/vtt"
_UNATTRIBUTED_FORMAT = "application/vnd.microsoft.graph.transcript+text"


async def _content(client: GraphServiceClient, handle: TranscriptHandle) -> tuple[bytes, bool]:
    """The transcript's bytes, and whether they carry speaker names.

    The attributed format is asked for first because it is the one worth having and the default. The
    single retry is Graph's own documented remedy for a tenant that permits transcripts and forbids
    speaker names — "Retry the same request asking for the unattributed format … which succeeds" —
    and it is scoped to that inner code alone: the tenant-wide switch reports itself the same way
    (`403 Forbidden`) and has no request-side workaround, so retrying it would be one wasted call
    and a message about the wrong remedy.

    Each attempt gets its own `graph_errors` rather than one around both. The branch is on a
    *classified* failure — the SDK's raw `APIError` has no inner code on it — so the translation has
    to have happened before the `except` can decide anything, which a block enclosing the whole
    function would defer until after it had already given up.
    """
    endpoint = (
        client.me.online_meetings.by_online_meeting_id(handle.meeting_id)
        .transcripts.by_call_transcript_id(handle.transcript_id)
        .content
    )
    try:
        with graph_errors():
            attributed = await endpoint.get(
                request_configuration=RequestConfiguration(headers=_accepting(_ATTRIBUTED_FORMAT))
            )
    except GraphForbidden as refusal:
        if refusal.inner_code != _SPEAKER_ATTRIBUTION_REFUSED:
            raise
        with graph_errors():
            unattributed = await endpoint.get(
                request_configuration=RequestConfiguration(headers=_accepting(_UNATTRIBUTED_FORMAT))
            )
        return (unattributed or b"", False)
    return (attributed or b"", True)


def _accepting(media_type: str) -> HeadersCollection:
    """A `HeadersCollection` of our own asking for `media_type`.

    Built per request: `RequestConfiguration.headers` defaults to one instance shared by every
    configuration in the process, so adding to the default would add to every other Graph request
    this connector makes. The generated builder adds its own `Accept` with `try_add`, which is a
    no-op once this one is present — which is how a format gets selected at all.
    """
    headers = HeadersCollection()
    headers.add("Accept", media_type)
    return headers


# One WebVTT cue's timing line. The hours field is optional in WebVTT and Teams omits it in some
# transcripts; the leading sign is what Microsoft's "negative offsets" note requires.
_TIMESTAMP = r"-?(?:\d+:)?\d{1,2}:\d{1,2}[.,]\d{1,3}"
_CUE_TIMING = re.compile(rf"^(?P<start>{_TIMESTAMP})\s*-->\s*(?P<end>{_TIMESTAMP})")

# A voice span, which is where a speaker's name lives: `<v Ada Lovelace>text</v>`. The class suffix
# (`<v.loud Ada>`) is part of WebVTT and Teams may emit it.
_VOICE = re.compile(r"<v(?:\.[^\s>]+)?\s+(?P<speaker>[^>]*)>(?P<said>.*?)(?:</v>|\Z)", re.DOTALL)

# Every other cue-payload tag: `<i>`, `<c.colorE5E5E5>`, `<00:00:01.000>` timestamps, `<lang en>`.
_MARKUP = re.compile(r"<[^>]*>")

_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def _turns(content: bytes, *, attributed: bool) -> list[TranscriptTurn]:
    """`content` as speaker-attributed, timestamped turns.

    One cue is one turn: Teams emits an utterance per cue, so merging them would be inventing a
    grouping Microsoft did not make. Anything that is not a cue — the `WEBVTT` header, `NOTE`,
    `STYLE` and `REGION` blocks, a cue identifier line — is skipped rather than guessed at, and a
    cue with a timing line but no words is dropped: an empty turn reads as a silence somebody sat
    through.

    `attributed` is what the request asked for, and it decides whether an unparsed `<v …>` could
    have been there at all — the unattributed format has none by construction.
    """
    text = content.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    turns: list[TranscriptTurn] = []
    for block in _BLANK_LINE.split(text):
        turn = _turn(block, attributed=attributed)
        if turn is not None:
            turns.append(turn)
    return turns


def _turn(block: str, *, attributed: bool) -> TranscriptTurn | None:
    """One cue block as a turn, or None if it is not a cue (or is one with nothing said)."""
    lines = [line for line in block.split("\n") if line.strip()]
    timing = next(
        ((index, match) for index, line in enumerate(lines) if (match := _CUE_TIMING.match(line))),
        None,
    )
    if timing is None:
        return None
    index, match = timing
    speaker, said = _spoken("\n".join(lines[index + 1 :]), attributed=attributed)
    if not said:
        return None
    return TranscriptTurn(
        speaker=speaker,
        start_seconds=_seconds(match.group("start")),
        end_seconds=_seconds(match.group("end")),
        text=said,
    )


def _spoken(payload: str, *, attributed: bool) -> tuple[str | None, str]:
    """A cue payload as (speaker, words).

    The voice span is read before the markup is stripped, because stripping it first would take the
    speaker's name with it. An attributed transcript whose cue carries no voice span keeps a null
    speaker rather than borrowing the previous turn's: Teams does leave some utterances
    unattributed, and attributing them to whoever spoke last would put words in someone's mouth.
    """
    voice = _VOICE.search(payload) if attributed else None
    speaker = voice.group("speaker").strip() if voice is not None else None
    said = voice.group("said") if voice is not None else payload
    words = html.unescape(_MARKUP.sub("", said)).replace("\xa0", " ")
    return (speaker or None, " ".join(words.split()))


def _seconds(timestamp: str) -> float:
    """A WebVTT timestamp as seconds, keeping its sign.

    `HH:MM:SS.mmm` and `MM:SS.mmm` are both legal; the comma decimal separator is not WebVTT but is
    what SubRip uses and costs nothing to accept.
    """
    negative = timestamp.startswith("-")
    parts = timestamp.lstrip("-").replace(",", ".").split(":")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return -total if negative else total


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Declare this tool against the shared Graph transport.

    `transport` is the long-lived `httpx.AsyncClient` from `create_graph_transport`; the tool
    borrows it per call and never owns it. `create_app` closes it on shutdown.
    """

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
                    "The transcript to read, exactly as list_meeting_transcripts reported its "
                    + "`uri`: `teams:///transcripts/{meeting_id}/{transcript_id}`. A meeting's "
                    + "`meeting_uri` is not one of these, and no other shape is readable here."
                ),
            ),
        ],
        offset: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "How many turns to skip. Start at 0 and pass the previous response's "
                    + "`next_offset` to continue through a long meeting."
                ),
            ),
        ] = 0,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_TURNS,
                description=(
                    "How many turns to return. Default 200, maximum "
                    + f"{MAX_TURNS}. Every call fetches the whole transcript from "
                    + "Microsoft, so widening this is cheaper than paging. It counts the turns "
                    + "left after `from_seconds`, `to_seconds` and `speaker`, not the meeting's."
                ),
            ),
        ] = 200,
        from_seconds: Annotated[
            float | None,
            Field(
                description=(
                    "Only turns reaching this moment or later, in seconds from when transcription "
                    + "began — the same scale as a turn's `start_seconds`, which is NOT a "
                    + "wall-clock time and NOT an offset from the start of the meeting. Inclusive, "
                    + "and matched by overlap: a turn already under way at this moment is kept "
                    + "whole rather than cut at it, which is usually the sentence that says what "
                    + "the stretch is about. Negative values are legal — Microsoft uses them for "
                    + "transcription that began after the conversation did. This narrows the "
                    + "answer, not the call: the whole transcript is fetched and parsed either way."
                )
            ),
        ] = None,
        to_seconds: Annotated[
            float | None,
            Field(
                description=(
                    "Only turns beginning at this moment or earlier, on the same scale and the "
                    + "same inclusive overlap rule: a turn still running at this moment is kept "
                    + "whole. Pair it with `from_seconds` to read one stretch of a long meeting, "
                    + "and keep the two in that order — a `from_seconds` later than this is "
                    + "refused rather than answered with an empty page."
                )
            ),
        ] = None,
        speaker: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only turns whose speaker's name contains this, ignoring case — `ada` matches "
                    + "`Ada Lovelace`. A substring rather than a whole name on purpose: Teams "
                    + "display names carry middle names, titles and tenant suffixes, and an exact "
                    + "match would answer 'they said nothing' to a spelling difference. **If the "
                    + "transcript's `speaker_attribution` is false this matches NOTHING** — that "
                    + "organisation records no speaker names, so every turn's `speaker` is null "
                    + "and no filter can match one. Read an empty answer together with that flag "
                    + "before concluding the person did not speak, and drop this filter to see the "
                    + "turns themselves. Omit it to read every speaker; a blank value is refused "
                    + "rather than read as 'everyone'."
                ),
            ),
        ] = None,
        graph_token: str = _TOKEN,
    ) -> Transcript:
        handle = transcript_handle(uri)
        if handle is None:
            raise ToolError(_NOT_A_TRANSCRIPT_HANDLE)
        # The two rules a schema cannot carry, refused here for the reason search_messages refuses
        # a criterion-less search: each would otherwise be answered with an empty page, and an
        # empty page is indistinguishable from a meeting in which nobody said anything.
        if from_seconds is not None and to_seconds is not None and from_seconds > to_seconds:
            raise ToolError(_INVERTED_TIME_WINDOW)
        if speaker is not None and not speaker.strip():
            raise ToolError(_BLANK_SPEAKER)
        with graph_tool_errors(*GRAPH_PERMISSIONS, not_found=_TRANSCRIPT_UNREADABLE):
            return await read_transcript(
                graph_client_for(transport, graph_token),
                handle=handle,
                offset=offset,
                limit=limit,
                from_seconds=from_seconds,
                to_seconds=to_seconds,
                speaker=speaker,
            )
