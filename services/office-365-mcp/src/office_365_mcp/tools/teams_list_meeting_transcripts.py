"""`teams_list_meeting_transcripts` — transcripts a Teams meeting holds and whether it was
transcribed.

TRAP: transcript access is a tenant-wide Teams switch, OFF by default and scoped to transcripts
alone, so an untouched tenant answers 403 here while `teams_list_meeting_recordings` succeeds. It
is admin action, not a permission.

TRAP: Graph can return an empty page that still carries a next link, so an empty page is not the
end of the collection. `graph_client/pagination.py` follows the link.

Graph offers no `$orderby` here, so rows are read up to MAX_ARTIFACT_SCAN and sorted before `limit`
cuts them. The one `$filter` Microsoft publishes for this collection is on `contentCorrelationId`,
in that lowercase `contentcorrelationId` spelling, and no date property appears in any `$filter`
context (https://learn.microsoft.com/en-us/graph/api/calltranscript-get, Example 11). Graph may
drop an unsupported parameter in silence (https://learn.microsoft.com/en-us/graph/query-parameters),
so the answer is checked against the filter that was sent.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, Self

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.call_transcript import CallTranscript
from msgraph.generated.users.item.online_meetings.item.transcripts.transcripts_request_builder import (  # noqa: E501
    TranscriptsRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared.handles import MeetingHandle, TranscriptHandle, meeting_handle
from office_365_mcp.shared.meetings import (
    MAX_ARTIFACT_SCAN,
    MEETING_PERMISSION,
    TRANSCRIPT_PERMISSION,
    newest_of,
    resolve_meeting,
    settled,
)
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_list_meeting_transcripts"

STEP_TRANSCRIPTS = "transcripts"

# `tests/test_layering.py` rule 4 forbids importing teams_read_transcript, so the transcript
# permission lives in `shared/meetings.py`. Entra redeems both under one token or neither.
GRAPH_PERMISSIONS: tuple[str, ...] = (MEETING_PERMISSION, TRANSCRIPT_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "meeting_uri": "teams:///meetings/https%3A%2F%2Fteams.microsoft.invalid%2Fl%2Fmeetup-join"
    + "%2F19%253ameeting_TjAwMDAwMDAwMDAwMA%2540thread.v2%2F0"
}

# Graph documents `$top` but publishes no ceiling, so this limit is ours.
MAX_TRANSCRIPTS = 50

type _TranscriptsQuery = TranscriptsRequestBuilder.TranscriptsRequestBuilderGetQueryParameters

_FILTER_IGNORED = (
    "Microsoft 365 answered this transcript listing with a transcript of a different call than "
    + "`content_correlation_id` named, which means it did not apply the filter this tool sent. "
    + "Microsoft documents that Graph can ignore a query parameter silently rather than refuse "
    + "it, so this tool checks the answer instead of trusting it. It reports no transcripts, "
    + "because the alternative is another occurrence's transcript presented as this call's. Call "
    + "teams_list_meeting_transcripts again without `content_correlation_id` and match each row's "
    + "own `content_correlation_id` instead."
)

# Graph-owned vocabularies (`meeting_type` here) stay `str`: Microsoft can add a member at any
# time. Bare assignment, not `type X = ...`: a PEP 695 alias publishes as a `$ref` into `$defs`,
# one hop away from the property a model reads.
TranscriptStatus = Literal["available", "not_ready", "not_transcribed", "meeting_not_found"]

_DESCRIPTION = """\
List a Teams meeting's transcripts, from the `meeting_uri` teams_list_chats reports. Call it to \
learn whether a meeting was transcribed. teams_read_transcript returns the words. Read `status` \
first: `not_ready` means wait, `not_transcribed` means none. To pick one occurrence out of a \
recurring series, pass `content_correlation_id` from a teams_list_meeting_recordings row: that \
one Microsoft 365 \
applies itself, and it is the route from a recording to the words of the same call. A tenant \
switch can block transcripts and never recordings, so try teams_list_meeting_recordings on \
refusal. Returns `status` and each transcript's `uri` and times. \
"""

_NOT_A_MEETING_HANDLE = (
    "teams_list_meeting_transcripts takes teams:///meetings/{join_web_url} from teams_list_chats, "
    + "not this. "
    + "Call teams_list_chats and use its `meeting_uri`. A `teams:///transcripts/...` handle is "
    + "teams_read_transcript's. This tool is what produces it. Retrying this value will fail "
    + "identically."
)


class TranscriptSummary(BaseModel):
    uri: str = Field(
        description="Handle for this transcript. Pass to teams_read_transcript to get the words."
    )
    transcript_id: str = Field(
        description="Transcript Graph id. Use `uri` to identify a transcript, not this alone."
    )
    started_at: datetime | None = Field(
        description=(
            "Transcription start. For recurring meetings, distinguishes one occurrence from "
            + "another."
        )
    )
    ended_at: datetime | None = Field(description="Transcription end.")
    content_correlation_id: str | None = Field(
        description="Microsoft's id linking this transcript to the recording of the same call."
    )

    @classmethod
    def from_transcript(cls, meeting_id: str, transcript: CallTranscript) -> Self:
        assert transcript.id is not None, "Graph returned a transcript with no id"
        return cls(
            uri=TranscriptHandle(meeting_id, transcript.id).uri,
            transcript_id=transcript.id,
            started_at=transcript.created_date_time,
            ended_at=transcript.end_date_time,
            content_correlation_id=transcript.content_correlation_id,
        )


class MeetingTranscripts(BaseModel):
    status: TranscriptStatus = Field(
        description=(
            "What was found and what to do next. One of:\n"
            + "- `available` — transcripts are listed, newest first.\n"
            + "- `not_ready` — nothing is there yet and something may still arrive. Wait and "
            + "call again later. This is NOT 'there is no transcript'. A meeting that "
            + "demonstrably ended is never reported this way, however far in the future a "
            + "recurring series runs. This is inferred. Microsoft publishes no availability "
            + "SLA.\n"
            + "- `not_transcribed` — the meeting is over. Nothing is there. Nothing is expected. "
            + "Retrying will not change this.\n"
            + "- `meeting_not_found` — Microsoft matched the join URL to no meeting this user can "
            + "see. Do not retry and do not rebuild the handle.\n"
            + "A refusal is about this user, not about the meeting: a participant can be refused "
            + "where the organizer succeeds."
        )
    )
    meeting_id: str | None = Field(
        description="Resolved meeting's Graph id, or null if `status` is `meeting_not_found`."
    )
    subject: str | None = Field(
        description="Meeting subject as Microsoft holds it. Confirms this is the right meeting."
    )
    meeting_type: str | None = Field(
        description=(
            "`scheduled`, `recurring`, `adhoc`, `meetNow`, `broadcast`, or null. When `recurring`, "
            + "read each row's `started_at` to tell one occurrence from another."
        )
    )
    started_at: datetime | None = Field(
        description=(
            "Meeting start. For recurring series, Microsoft's single value for the whole series."
        )
    )
    ended_at: datetime | None = Field(description="Meeting end (same caveat as `started_at`).")
    transcripts: list[TranscriptSummary] = Field(
        description=(
            "The meeting's transcripts, newest first. The order is over "
            + f"every transcript this call read (up to {MAX_ARTIFACT_SCAN}), not over one page of "
            + "Microsoft's answer. For meetings with fewer transcripts than that cap — all but "
            + "series recorded daily for most of a year — the first entry is the meeting's "
            + "latest. Past the cap the first entry is the latest of what was READ. Microsoft "
            + "returns this collection in its own order and offers no `$orderby`. Set "
            + "`include_scan_completeness` to learn if the read reached the end. As many as "
            + "`limit` "
            + "means the meeting can hold older ones. Fewer means it holds no more than was "
            + "read. Empty for every status other than `available`."
        )
    )
    scan_incomplete: bool | None = Field(
        description=(
            f"Whether read stopped at {MAX_ARTIFACT_SCAN} transcripts (true), read all (false), or "
            + "null if not requested. Set only when `include_scan_completeness` is true. True "
            + "means "
            + "transcripts ordered over those read, not all. False means order and absence are "
            + "exact."
        )
    )


async def teams_list_meeting_transcripts(
    client: GraphServiceClient,
    *,
    handle: MeetingHandle,
    content_correlation_id: str | None = None,
    limit: int,
    include_scan_completeness: bool,
) -> MeetingTranscripts:
    """Transcripts of the meeting `handle` addresses. At most two Graph requests: resolve, list."""
    assert 1 <= limit <= MAX_TRANSCRIPTS, f"limit must be within 1..{MAX_TRANSCRIPTS}, got {limit}"

    with graph_errors(TOOL_NAME):
        meeting = await resolve_meeting(client, handle)
        if meeting is None or meeting.id is None:
            return MeetingTranscripts(
                status="meeting_not_found",
                meeting_id=None,
                subject=None,
                meeting_type=None,
                started_at=None,
                ended_at=None,
                transcripts=[],
                scan_incomplete=False if include_scan_completeness else None,
            )
        with graph_step(STEP_TRANSCRIPTS):
            first_page = await client.me.online_meetings.by_online_meeting_id(
                meeting.id
            ).transcripts.get(request_configuration=_paired_with(content_correlation_id))
            assert first_page is not None, "Graph answered a transcript listing with no collection"
            collected = await newest_of(first_page, client, limit=limit)

    found = collected.items
    _make_sure_the_filter_was_applied(found, content_correlation_id)
    return MeetingTranscripts(
        status="available" if found else _absence(settled=settled(meeting)),
        meeting_id=meeting.id,
        subject=meeting.subject,
        # meetingType is a generated enum. Unknown values deserialize to None, not to an error.
        meeting_type=meeting.meeting_type,
        started_at=meeting.start_date_time,
        ended_at=meeting.end_date_time,
        transcripts=[
            TranscriptSummary.from_transcript(meeting.id, transcript) for transcript in found
        ],
        scan_incomplete=collected.capped if include_scan_completeness else None,
    )


def _paired_with(
    content_correlation_id: str | None,
) -> RequestConfiguration[_TranscriptsQuery] | None:
    """The one `$filter` this collection documents, or None when the caller named no call.

    `contentcorrelationId` is Microsoft's own lowercase spelling of the property.
    """
    if content_correlation_id is None:
        return None
    return RequestConfiguration[_TranscriptsQuery](
        query_parameters=TranscriptsRequestBuilder.TranscriptsRequestBuilderGetQueryParameters(
            filter=f"contentcorrelationId eq '{odata_literal(content_correlation_id)}'"
        )
    )


def _make_sure_the_filter_was_applied(
    found: list[CallTranscript], content_correlation_id: str | None
) -> None:
    """Refuse an answer holding a transcript of another call. See the module docstring.

    A null `contentCorrelationId` passes: it is not evidence about the filter. A DIFFERENT id is,
    and it is what a dropped filter produces on a recurring series.
    """
    if content_correlation_id is None:
        return
    # Case-folded: the answer echoes the spelling Microsoft 365 holds, not the one filtered with.
    wanted = content_correlation_id.casefold()
    for transcript in found:
        recorded = transcript.content_correlation_id
        if recorded is not None and recorded.casefold() != wanted:
            raise ToolError(_FILTER_IGNORED)


def _absence(*, settled: bool) -> TranscriptStatus:
    """Which empty answer: the meeting is over and nothing came, or it is too soon to say."""
    return "not_transcribed" if settled else "not_ready"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List a Meeting's Transcripts",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def list_transcripts(
        meeting_uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Meeting handle from teams_list_chats: teams:///meetings/{join_web_url}. Copy "
                    + "verbatim."
                ),
            ),
        ],
        content_correlation_id: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Only the transcript(s) Microsoft paired with one particular call. Copy the "
                    + "value verbatim out of a teams_list_meeting_recordings row, which is where "
                    + "it comes from: it is Microsoft's own link between a recording and the "
                    + 'transcript of the SAME call, so this is how "get me the words of that '
                    + '47-minute recording" is asked. Do not construct one. This is the only '
                    + "bound Microsoft 365 applies itself here, so on a recurring series it beats "
                    + "reading every row's `started_at` for picking one occurrence out. Usually "
                    + "one transcript, but not promised: Microsoft's own documented response "
                    + "shows several sharing one pairing id, so treat the answer as a list."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_TRANSCRIPTS,
                description=(
                    f"How many transcripts to return. Default 20, maximum {MAX_TRANSCRIPTS}. These "
                    + "are the NEWEST that many of the meeting. All transcripts are read (up to "
                    + f"{MAX_ARTIFACT_SCAN}, the call's whole cost) and ordered before this cuts "
                    + "them. Past that cap they are the newest OF THE ONES READ, not the meeting's "
                    + "newest."
                ),
            ),
        ] = 20,
        include_scan_completeness: Annotated[
            bool,
            Field(
                description=(
                    "Report whether read reached the end of transcripts, as `scan_incomplete`. Off "
                    + "by default."
                )
            ),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> MeetingTranscripts:
        handle = meeting_handle(meeting_uri)
        if handle is None:
            raise ToolError(_NOT_A_MEETING_HANDLE)
        return await teams_list_meeting_transcripts(
            client,
            handle=handle,
            content_correlation_id=content_correlation_id,
            limit=limit,
            include_scan_completeness=include_scan_completeness,
        )
