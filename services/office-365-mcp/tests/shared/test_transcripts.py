"""`shared/transcripts.py`: reading a page of turns, independent of either reader."""

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphResponseTooLarge
from office_365_mcp.shared import transcripts

_PATH = "/me/onlineMeetings/meeting-1/transcripts/transcript-1/content"

_VTT = """WEBVTT

-00:00:02.500 --> 00:00:01.250
<v Ada Lovelace>Sorry, joining late &amp; muted.</v>

00:00:16.246 --> 00:00:19.900
<v.loud Grace Hopper>We should <i>raise</i> the floor price.</v>

00:01:02.000 --> 00:01:04.500
<v Ada Lovelace>Agreed.</v>

01:00:03.000 --> 01:00:04.000
<v Ada Lovelace></v>
"""

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
            ("Ada Lovelace", -2.5, 1.25, "Sorry, joining late & muted."),
            ("Grace Hopper", 16.246, 19.9, "We should raise the floor price."),
            ("Ada Lovelace", 62.0, 64.5, "Agreed."),
        ]
        assert page.speaker_attribution is True
        assert page.next_offset is None, "an empty voice cue is not a turn, and not a next page"

    async def test_a_limit_pages_the_turns_and_next_offset_continues_them(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(return_value=httpx.Response(200, content=_VTT.encode()))

        first = await _read(client, transport, limit=2)
        second = await _read(client, transport, limit=2, offset=first.next_offset or 0)

        assert [t.text for t in first.turns] == [
            "Sorry, joining late & muted.",
            "We should raise the floor price.",
        ]
        assert first.next_offset == 2
        assert [t.text for t in second.turns] == ["Agreed."]
        assert second.next_offset is None

    @pytest.mark.parametrize(
        ("speaker", "from_seconds", "to_seconds", "texts"),
        [
            ("grace", None, None, ["We should raise the floor price."]),
            (None, 60.0, None, ["Agreed."]),
            (None, None, 0.0, ["Sorry, joining late & muted."]),
            (None, 10.0, 30.0, ["We should raise the floor price."]),
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
        def respond(request: httpx.Request) -> httpx.Response:
            if request.headers["accept"] == "text/vtt":
                return httpx.Response(403, json=_ATTRIBUTION_OFF)
            return httpx.Response(200, content=b"00:00:01.000 --> 00:00:02.000\nHello there.\n")

        _ = graph.get(_PATH).mock(side_effect=respond)

        page = await _read(client, transport)

        assert page.speaker_attribution is False
        assert [(t.speaker, t.text) for t in page.turns] == [(None, "Hello there.")]

    async def test_a_transcript_over_the_ceiling_is_refused_before_any_turn_is_read(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(transcripts, "MAX_TRANSCRIPT_BYTES", 64)
        _ = graph.get(_PATH).mock(return_value=httpx.Response(200, content=_VTT.encode()))

        with pytest.raises(GraphResponseTooLarge) as refused:
            _ = await _read(client, transport)

        text = transcripts.too_large(refused.value, noun="meeting", lister="teams_list_x")
        assert "the meeting was silent" in text
        assert "teams_list_x still lists this transcript" in text
