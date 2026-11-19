"""One page of a Teams meeting transcript, read off a streamed file rather than held whole."""

from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

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
    TranscriptPage,
    bad_filters,
    read_page,
    too_large,
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
    + "`meeting_uri`, and do not use a Teams message handle. A `teams:///calltranscripts/...` "
    + "handle belongs to teams_read_call_transcript. A retry will fail identically."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this transcript. The handle is well formed. A one-off "
    + "meeting expires after about 60 days, and its transcripts expire with it. Call "
    + "teams_list_meeting_transcripts again to see what remains. If the transcript is not in "
    + "that list, a retry will not help."
)


class Transcript(TranscriptPage):
    uri: str = Field(description="This tool echoes back the handle that it read.")
    meeting_id: str = Field(description="This value is the meeting Graph id.")
    transcript_id: str = Field(description="This value is the transcript Graph id.")


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
    content = (
        client.me.online_meetings.by_online_meeting_id(handle.meeting_id)
        .transcripts.by_call_transcript_id(handle.transcript_id)
        .content
    )
    try:
        with graph_errors():
            page = await read_page(
                client,
                transport,
                content,
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
            speaker_attribution=page.speaker_attribution,
            turns=page.turns,
            next_offset=page.next_offset,
        )
    except GraphResponseTooLarge as refusal:
        refused = too_large(refusal, noun="meeting", lister="teams_list_meeting_transcripts")
    raise ToolError(refused)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Teams: Read a Meeting Transcript",
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
