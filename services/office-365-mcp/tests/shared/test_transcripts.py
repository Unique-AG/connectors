"""`shared/transcripts.py`: reading a page of turns, independent of either reader."""

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.shared import transcripts

_PATH = "/me/onlineMeetings/meeting-1/transcripts/transcript-1/content"

_VTT = """WEBVTT

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

_ADA_FIRST = "Sorry, joining late & muted."
_GRACE = "We should raise the floor price by three per cent."
_AGREED = "Agreed <that> works."
_NOBODY = "Nobody was attributed for this one."

_ATTRIBUTION_OFF = {
    "error": {
        "code": "Forbidden",
        "message": "Speaker-attributed content is disabled.",
        "innerError": {"code": "SpeakerAttributionNotAllowed"},
    }
}


async def _read(
    client: GraphServiceClient,
    transport: httpx.AsyncClient,
    *,
    offset: int = 0,
    limit: int = 200,
    from_seconds: float | None = None,
    to_seconds: float | None = None,
    speaker: str | None = None,
) -> transcripts.TranscriptPage:
    content = (
        client.me.online_meetings.by_online_meeting_id("meeting-1")
        .transcripts.by_call_transcript_id("transcript-1")
        .content
    )
    return await transcripts.read_page(
        client,
        transport,
        content,
        offset=offset,
        limit=limit,
        from_seconds=from_seconds,
        to_seconds=to_seconds,
        speaker=speaker,
    )


class TestReadingAPage:
    async def test_a_cue_becomes_a_turn_with_the_markup_removed_and_an_empty_cue_dropped(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(return_value=httpx.Response(200, content=_VTT.encode()))

        page = await _read(client, transport)

        assert [(t.speaker, t.start_seconds, t.end_seconds, t.text) for t in page.turns] == [
            ("Ada Lovelace", -2.5, 1.25, _ADA_FIRST),
            ("Grace Hopper", 16.246, 19.9, _GRACE),
            ("Ada Lovelace", 62.0, 64.5, _AGREED),
            (None, 3600.0, 3602.0, _NOBODY),
        ]
        assert page.speaker_attribution is True
        assert page.next_offset is None

    async def test_a_limit_pages_the_turns_and_next_offset_continues_them(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(return_value=httpx.Response(200, content=_VTT.encode()))

        first = await _read(client, transport, limit=2)
        second = await _read(client, transport, limit=2, offset=first.next_offset or 0)

        assert [t.text for t in first.turns] == [_ADA_FIRST, _GRACE]
        assert first.next_offset == 2
        assert [t.text for t in second.turns] == [_AGREED, _NOBODY]
        assert second.next_offset is None, "only an empty cue follows, and that is not a turn"

    async def test_a_page_that_ends_on_the_last_match_has_no_next_offset(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(return_value=httpx.Response(200, content=_VTT.encode()))

        page = await _read(client, transport, limit=4)

        assert len(page.turns) == 4
        assert page.next_offset is None

    @pytest.mark.parametrize(
        ("speaker", "from_seconds", "to_seconds", "texts"),
        [
            ("grace", None, None, [_GRACE]),
            (None, 60.0, None, [_AGREED, _NOBODY]),
            (None, None, 0.0, [_ADA_FIRST]),
            (None, 19.9, 62.0, [_GRACE, _AGREED]),
        ],
    )
    async def test_the_filters_select_turns_by_speaker_and_by_overlap_with_the_window(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        speaker: str | None,
        from_seconds: float | None,
        to_seconds: float | None,
        texts: list[str],
    ) -> None:
        _ = graph.get(_PATH).mock(return_value=httpx.Response(200, content=_VTT.encode()))

        page = await _read(
            client, transport, speaker=speaker, from_seconds=from_seconds, to_seconds=to_seconds
        )

        assert [t.text for t in page.turns] == texts

    async def test_a_tenant_that_forbids_speaker_names_gets_the_turns_without_them(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        attempts: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            attempts.append(request.headers["accept"])
            if request.headers["accept"] == "text/vtt":
                return httpx.Response(403, json=_ATTRIBUTION_OFF)
            return httpx.Response(200, content=b"00:00:01.000 --> 00:00:02.000\nHello there.\n")

        _ = graph.get(_PATH).mock(side_effect=respond)

        page = await _read(client, transport)

        assert attempts == ["text/vtt", "application/vnd.microsoft.graph.transcript+text"]
        assert page.speaker_attribution is False
        assert [(t.speaker, t.text) for t in page.turns] == [(None, "Hello there.")]
