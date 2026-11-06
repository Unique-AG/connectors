"""One page of a Teams meeting transcript, read off a streamed file rather than held whole."""

from collections.abc import Mapping
from pathlib import Path
from tempfile import gettempdir
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.headers_collection import HeadersCollection
from kiota_abstractions.request_information import RequestInformation
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphResponseTooLarge, graph_errors
from office_365_mcp.shared.handles import TranscriptHandle, transcript_handle
from office_365_mcp.shared.meetings import TRANSCRIPT_PERMISSION
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.transcripts import (
    MAX_TRANSCRIPT_BYTES,
    FromSeconds,
    Limit,
    Offset,
    Speaker,
    ToSeconds,
    TranscriptTurn,
    bad_filters,
    read_turns,
)

TOOL_NAME = "teams_read_transcript"

GRAPH_PERMISSIONS: tuple[str, ...] = (TRANSCRIPT_PERMISSION,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///transcripts/MSpiYTMyMWUwZC03OWVlLTQ3OGQtOGUyOC04NWExOTUwN2Y0NTYqMCoq"
    + "/MSMjMCMjSYNTHETIC0002"
}


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
    assert limit >= 1, f"limit must be at least 1, got {limit}"
    assert offset >= 0, f"offset must not be negative, got {offset}"
    assert from_seconds is None or to_seconds is None or from_seconds <= to_seconds, (
        f"from_seconds must not be after to_seconds, got {from_seconds} and {to_seconds}"
    )

    endpoint = (
        client.me.online_meetings.by_online_meeting_id(handle.meeting_id)
        .transcripts.by_call_transcript_id(handle.transcript_id)
        .content
    )

    def request_for(headers: HeadersCollection) -> RequestInformation:
        return endpoint.to_get_request_information(
            RequestConfiguration[QueryParameters](headers=headers)
        )

    scratch = Path(gettempdir())
    try:
        with graph_errors(TOOL_NAME):
            turns, next_offset, attributed = await read_turns(
                client,
                transport,
                request_for,
                directory=scratch,
                max_bytes=MAX_TRANSCRIPT_BYTES,
                offset=offset,
                limit=limit,
                from_seconds=from_seconds,
                to_seconds=to_seconds,
                speaker=speaker,
            )
        return Transcript(
            uri=handle.uri,
            meeting_id=handle.meeting_id,
            transcript_id=handle.transcript_id,
            speaker_attribution=attributed,
            turns=turns,
            next_offset=next_offset,
        )
    except GraphResponseTooLarge as refusal:
        refused = _too_large(refusal)
    raise ToolError(refused)


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
        offset: Offset = 0,
        limit: Limit = 200,
        from_seconds: FromSeconds = None,
        to_seconds: ToSeconds = None,
        speaker: Speaker = None,
        client: GraphServiceClient = graph,
    ) -> Transcript:
        handle = transcript_handle(uri)
        if handle is None:
            raise ToolError(_NOT_A_TRANSCRIPT_HANDLE)
        if refusal := bad_filters(from_seconds, to_seconds, speaker):
            raise ToolError(refusal)
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
