"""One page of a Teams call transcript, read off a streamed file rather than held whole."""

from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import GraphResponseTooLarge, graph_errors
from office_365_mcp.shared.handles import CallTranscriptHandle, call_transcript_handle
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.transcripts import (
    CALL_TRANSCRIPT_PERMISSION,
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

TOOL_NAME = "teams_read_call_transcript"

GRAPH_PERMISSIONS: tuple[str, ...] = (CALL_TRANSCRIPT_PERMISSION,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///calltranscripts/SYNTHETIC-CALL-0001" + "/MSMjMCMjSYNTHETIC0002"
}


_DESCRIPTION = f"""\
Returns the spoken turns of one Teams call transcript. Use this tool to read what a \
call said or decided. Each turn has a start time and an end time in seconds. Each turn can \
have a speaker name. Use the `uri` that teams_list_call_transcripts reports. \
A meeting transcript handle is not valid here.

Notes:
- Only a call the signed-in user was on. Readable only when someone in that user's organization \
started the transcription (a 1:1 call) or started the call (a group call).
- The transcript appears 1 to 2 minutes after the call. teams_list_call_transcripts, with \
`chat_id`, can name group calls that ended without a transcription.
- If `speaker_attribution` is false, every `speaker` is null. A `speaker` filter then matches \
nothing.
- `from_seconds` must not be later than `to_seconds`. If `from_seconds` is later than \
`to_seconds`, this tool refuses the call.
- If a transcript is larger than {MAX_TRANSCRIPT_BYTES // (1024 * 1024)} MB, this tool refuses \
it. No argument makes the call smaller.
"""

_NOT_A_CALL_TRANSCRIPT_HANDLE = (
    "teams_read_call_transcript takes the handle teams:///calltranscripts/"
    + "{call_id}/{transcript_id}. teams_list_call_transcripts reports that handle. This "
    + "value has a different shape. Call teams_list_call_transcripts and use its `uri`. A "
    + "meeting transcript handle, teams:///transcripts/{meeting_id}/{transcript_id}, goes to "
    + "teams_read_transcript. Do not use a Teams message handle. A retry will fail identically."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this transcript. The handle is well formed. This happens "
    + "when someone outside your organization started the transcription, or the transcript was "
    + "deleted. Call teams_list_call_transcripts again to see what remains. If the transcript "
    + "is not in that list, a retry will not help."
)

GRAPH_FORBIDDEN = (
    "Microsoft 365 will not return this transcript. The handle is well formed. This transcript "
    + "belongs to a call you were not on, or you no longer have access. Call "
    + "teams_list_call_transcripts again and use a handle from that list. A retry of this "
    + "handle will fail identically."
)


class CallTranscript(TranscriptPage):
    uri: str = Field(description="This tool echoes back the handle that it read.")
    call_id: str = Field(description="This value is the call Graph id.")
    transcript_id: str = Field(description="This value is the transcript Graph id.")


async def teams_read_call_transcript(
    client: GraphServiceClient,
    transport: httpx.AsyncClient,
    *,
    handle: CallTranscriptHandle,
    offset: int,
    limit: int,
    from_seconds: float | None = None,
    to_seconds: float | None = None,
    speaker: str | None = None,
) -> CallTranscript:
    content = (
        client.me.adhoc_calls.by_adhoc_call_id(handle.call_id)
        .transcripts.by_call_transcript_id(handle.transcript_id)
        .content
    )
    try:
        with graph_errors(TOOL_NAME):
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
        return CallTranscript(
            uri=handle.uri,
            call_id=handle.call_id,
            transcript_id=handle.transcript_id,
            speaker_attribution=page.speaker_attribution,
            turns=page.turns,
            next_offset=page.next_offset,
        )
    except GraphResponseTooLarge as refusal:
        refused = too_large(refusal, noun="call", lister="teams_list_call_transcripts")
    raise ToolError(refused)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Teams: Read a Call Transcript",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def read_call_transcript(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The transcript handle from teams_list_call_transcripts: "
                    "`teams:///calltranscripts/{call_id}/{transcript_id}`. A meeting transcript "
                    "handle is not valid here."
                ),
            ),
        ],
        offset: Offset = 0,
        limit: Limit = 200,
        from_seconds: FromSeconds = None,
        to_seconds: ToSeconds = None,
        speaker: Speaker = None,
        client: GraphServiceClient = graph,
    ) -> CallTranscript:
        handle = call_transcript_handle(uri)
        if handle is None:
            raise ToolError(_NOT_A_CALL_TRANSCRIPT_HANDLE)
        if refusal := bad_filters(from_seconds, to_seconds, speaker):
            raise ToolError(refusal)
        return await teams_read_call_transcript(
            client,
            transport,
            handle=handle,
            offset=offset,
            limit=limit,
            from_seconds=from_seconds,
            to_seconds=to_seconds,
            speaker=speaker,
        )
