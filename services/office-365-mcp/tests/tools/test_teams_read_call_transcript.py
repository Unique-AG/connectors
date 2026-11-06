"""`teams_read_call_transcript`: the refusals, the speaker fallback, and one read."""

from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import CallTranscriptHandle
from office_365_mcp.tools import teams_read_call_transcript as reader

CALL_ID = "SYNTHETIC-CALL-0001"
_TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0001"
_CONTENT = f"/me/adhocCalls/{CALL_ID}/transcripts/{_TRANSCRIPT_ID}/content"
_MEETING_TRANSCRIPT = "teams:///transcripts/SYNTHETIC-MEETING-0001/MSMjMCMjSYNTHETIC0001"

_NOT_ON_THE_CALL = {
    "error": {
        "code": "Forbidden",
        "message": "UnknownError",
    }
}

_ATTRIBUTION_OFF = {
    "error": {
        "code": "Forbidden",
        "message": (
            "Speaker-attributed transcript content is disabled for this tenant. Retry with Accept "
            + "'application/vnd.microsoft.graph.transcript+text'."
        ),
        "innerError": {"code": "SpeakerAttributionNotAllowed"},
    }
}

TRANSCRIPT_VTT = """WEBVTT

NOTE this transcript is synthetic

-00:00:02.500 --> 00:00:01.250
<v Ada Lovelace>Sorry, joining late &amp; muted.</v>

f1f0c0de-0001
00:00:16.246 --> 00:00:19.900
<v.loud Grace Hopper>We should <i>raise</i> the floor price
by three per cent.</v>

f1f0c0de-0002
00:01:02.000 --> 00:01:04.500
<v Ada Lovelace>Agreed &lt;that&gt; works.</v>

f1f0c0de-0003
01:00:00.000 --> 01:00:02.000
Nobody was attributed for this one.

f1f0c0de-0004
01:00:03.000 --> 01:00:04.000
<v Ada Lovelace></v>
"""

TRANSCRIPT_UNATTRIBUTED = """00:00:16.246 --> 00:00:19.900
We should raise the floor price by three per cent.

00:01:02.000 --> 00:01:04.500
Agreed that works.
"""


def _transcript() -> CallTranscriptHandle:
    return CallTranscriptHandle(CALL_ID, _TRANSCRIPT_ID)


class TestReadingTheWords:
    async def test_vtt_becomes_speaker_attributed_timestamped_turns(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_CONTENT).mock(
            return_value=httpx.Response(
                200, content=TRANSCRIPT_VTT.encode(), headers={"content-type": "text/vtt"}
            )
        )
        handle = _transcript()

        read = await reader.teams_read_call_transcript(
            client, transport, handle=handle, offset=0, limit=200
        )

        assert route.calls.last.request.url.path.endswith(_CONTENT)
        assert route.calls.last.request.headers["accept"] == "text/vtt"
        assert read.call_id == CALL_ID
        assert read.transcript_id == _TRANSCRIPT_ID
        assert read.uri == handle.uri
        assert read.speaker_attribution is True
        assert [(turn.speaker, turn.text) for turn in read.turns] == [
            ("Ada Lovelace", "Sorry, joining late & muted."),
            ("Grace Hopper", "We should raise the floor price by three per cent."),
            ("Ada Lovelace", "Agreed <that> works."),
            (None, "Nobody was attributed for this one."),
        ]
        assert read.turns[0].start_seconds == -2.5, "transcription began mid-conversation"
        assert (read.turns[1].start_seconds, read.turns[1].end_seconds) == (16.246, 19.9)
        assert read.next_offset is None

    async def test_a_tenant_that_forbids_speaker_names_degrades_instead_of_failing(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        """Graph's own documented remedy is to ask again for the unattributed format."""
        attempts: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            accept = request.headers["accept"]
            attempts.append(accept)
            if accept == "text/vtt":
                return httpx.Response(403, json=_ATTRIBUTION_OFF)
            return httpx.Response(200, content=TRANSCRIPT_UNATTRIBUTED.encode())

        graph.get(_CONTENT).mock(side_effect=respond)

        read = await reader.teams_read_call_transcript(
            client, transport, handle=_transcript(), offset=0, limit=200
        )

        assert attempts == ["text/vtt", "application/vnd.microsoft.graph.transcript+text"]
        assert read.speaker_attribution is False
        assert [turn.speaker for turn in read.turns] == [None, None]
        assert read.turns[0].text == "We should raise the floor price by three per cent."
        assert read.turns[0].start_seconds == 16.246, "the timings survive; only the names are gone"


class TestTheRefusals:
    async def test_a_meeting_transcript_handle_points_at_the_meeting_reader(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        reader.register(mcp, transport)
        tool = await mcp.get_tool(reader.TOOL_NAME)
        assert isinstance(tool, FunctionTool)

        with pytest.raises(ToolError) as refused:
            _ = cast(
                "object",
                await tool.fn(uri=_MEETING_TRANSCRIPT, client=client),
            )

        text = str(refused.value)
        assert "teams:///calltranscripts/{call_id}/{transcript_id}" in text
        assert "teams_read_transcript" in text
        assert "teams:///transcripts/{meeting_id}/{transcript_id}" in text
        assert len(graph.calls) == 0

    async def test_a_transcript_another_organization_started_or_deleted_is_not_found(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_CONTENT).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "UnknownError"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await reader.teams_read_call_transcript(
                client, transport, handle=_transcript(), offset=0, limit=200
            )

        assert route.call_count == 1

    async def test_a_call_the_reader_was_not_on_is_forbidden(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_CONTENT).mock(return_value=httpx.Response(403, json=_NOT_ON_THE_CALL))

        with pytest.raises(GraphForbidden) as raised:
            _ = await reader.teams_read_call_transcript(
                client, transport, handle=_transcript(), offset=0, limit=200
            )

        assert raised.value.inner_code is None
        assert route.call_count == 1, "no second format: this is not speaker attribution"

    async def test_a_transcript_longer_than_the_ceiling_is_refused_in_this_tools_own_words(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Graph declares the length, so this is refused before a byte of it is read."""
        monkeypatch.setattr(reader, "MAX_TRANSCRIPT_BYTES", 64)
        route = graph.get(_CONTENT).mock(
            return_value=httpx.Response(200, content=TRANSCRIPT_VTT.encode())
        )

        with pytest.raises(ToolError) as raised:
            _ = await reader.teams_read_call_transcript(
                client, transport, handle=_transcript(), offset=0, limit=200
            )

        text = str(raised.value)
        assert "64" in text, "the ceiling it was measured against"
        assert f"{len(TRANSCRIPT_VTT.encode())} bytes" in text
        assert "no argument makes it smaller" in text
        assert "the call was silent" in text
        assert "teams_list_call_transcripts" in text
        assert "meeting" not in text
        assert "rejected this request" not in text, "not the seam's generic advice"
        assert raised.value.__cause__ is None, "raised after the failure was handled"
        assert route.called
