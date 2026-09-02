"""`teams_read_transcript`: the words that come back, and what narrows them."""

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared import identity
from office_365_mcp.shared.handles import TranscriptHandle
from office_365_mcp.tools import teams_read_transcript as reader

from .conftest import ME

MEETING_ID = "MSpiYTMyMWUwZC03OWVlLTQ3OGQtOGUyOC04NWExOTUwN2Y0NTYqMCoq"

_TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0001"
_CONTENT = f"/me/onlineMeetings/{MEETING_ID}/transcripts/{_TRANSCRIPT_ID}/content"

_TENANT_SWITCH_OFF = {
    "error": {
        "code": "Forbidden",
        "message": "Graph API access to transcripts is disabled for this tenant.",
        "innerError": {"code": "GraphAccessToTranscriptsDisabled"},
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

# Everything the parser has to survive: the `WEBVTT` header, a NOTE block, cue identifier lines, a
# voice tag with a class, a cue wrapped over two lines, escaped entities, inline markup, a cue
# nobody was attributed for, an empty one, and the negative offset Microsoft documents for
# transcription that started mid-conversation.
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


def _transcript() -> TranscriptHandle:
    return TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID)


def _spoken(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_CONTENT).mock(
        return_value=httpx.Response(200, content=TRANSCRIPT_VTT.encode())
    )


def _spoken_by_nobody(graph: respx.MockRouter) -> respx.Route:
    """Serving unattributed bytes to the attributed request would report `speaker_attribution`
    true, which is the field a caller reads to learn why a speaker filter matched nothing."""

    def respond(request: httpx.Request) -> httpx.Response:
        if request.headers["accept"] == "text/vtt":
            return httpx.Response(403, json=_ATTRIBUTION_OFF)
        return httpx.Response(200, content=TRANSCRIPT_UNATTRIBUTED.encode())

    return graph.get(_CONTENT).mock(side_effect=respond)


class TestReadingTheWords:
    async def test_vtt_becomes_speaker_attributed_timestamped_turns(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_CONTENT).mock(
            return_value=httpx.Response(
                200, content=TRANSCRIPT_VTT.encode(), headers={"content-type": "text/vtt"}
            )
        )

        read = await reader.teams_read_transcript(
            client,
            handle=TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID),
            offset=0,
            limit=200,
        )

        assert read.speaker_attribution is True
        assert [(turn.speaker, turn.text) for turn in read.turns] == [
            ("Ada Lovelace", "Sorry, joining late & muted."),
            ("Grace Hopper", "We should raise the floor price by three per cent."),
            ("Ada Lovelace", "Agreed <that> works."),
            (None, "Nobody was attributed for this one."),
        ]
        assert read.turns[0].start_seconds == -2.5, "transcription began mid-conversation"
        assert (read.turns[1].start_seconds, read.turns[1].end_seconds) == (16.246, 19.9)
        assert read.turns[3].start_seconds == 3600.0, "an hour in, from the HH:MM:SS form"
        assert read.next_offset is None
        assert route.calls.last.request.headers["accept"] == "text/vtt"

    async def test_the_turns_page_without_refusing_a_long_meeting(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_CONTENT).mock(return_value=httpx.Response(200, content=TRANSCRIPT_VTT.encode()))
        handle = TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID)

        first = await reader.teams_read_transcript(client, handle=handle, offset=0, limit=2)
        second = await reader.teams_read_transcript(
            client, handle=handle, offset=first.next_offset or 0, limit=2
        )

        assert first.next_offset == 2, "the offset is the whole of 'there are more turns'"
        assert [turn.speaker for turn in first.turns] == ["Ada Lovelace", "Grace Hopper"]
        assert second.next_offset is None, "and null on the last page is the whole of saying so"
        assert [turn.speaker for turn in second.turns] == ["Ada Lovelace", None]

    async def test_a_tenant_that_forbids_speaker_names_degrades_instead_of_failing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph's own documented remedy is to ask again for the unattributed format.
        `services/teams-mcp` hardcodes `Accept: text/vtt` and loses the transcript entirely."""
        attempts: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            accept = request.headers["accept"]
            attempts.append(accept)
            if accept == "text/vtt":
                return httpx.Response(403, json=_ATTRIBUTION_OFF)
            return httpx.Response(200, content=TRANSCRIPT_UNATTRIBUTED.encode())

        graph.get(_CONTENT).mock(side_effect=respond)

        read = await reader.teams_read_transcript(
            client,
            handle=TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID),
            offset=0,
            limit=200,
        )

        assert attempts == ["text/vtt", "application/vnd.microsoft.graph.transcript+text"]
        assert read.speaker_attribution is False
        assert [turn.speaker for turn in read.turns] == [None, None]
        assert read.turns[0].text == "We should raise the floor price by three per cent."
        assert read.turns[0].start_seconds == 16.246, "the timings survive; only the names are gone"

    async def test_the_tenant_switch_is_not_retried_in_another_format(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft publishes no request-side workaround for this one, so the retry above must be
        scoped to the inner code and not to 403."""
        route = graph.get(_CONTENT).mock(return_value=httpx.Response(403, json=_TENANT_SWITCH_OFF))

        with pytest.raises(GraphForbidden) as raised:
            _ = await reader.teams_read_transcript(
                client,
                handle=TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID),
                offset=0,
                limit=200,
            )

        assert raised.value.inner_code == "GraphAccessToTranscriptsDisabled"
        assert route.call_count == 1

    async def test_the_accept_header_is_not_added_to_every_other_graph_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """kiota's `RequestConfiguration.headers` defaults to ONE `HeadersCollection` shared by
        every configuration in the process, and the generated builders' own
        `try_add("Accept", "application/json")` cannot take a polluted default back.

        `shared/identity.py`'s `GET /me` is the witness because it passes a `RequestConfiguration`
        of its own; a call passing none would keep passing while the leak came back.
        """
        _spoken(graph)
        profile = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))

        _ = await reader.teams_read_transcript(client, handle=_transcript(), offset=0, limit=200)
        _ = await identity.signed_in_user(client)

        assert "text/vtt" not in profile.calls.last.request.headers["accept"]

    async def test_an_empty_transcript_is_no_turns_rather_than_a_blank_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_CONTENT).mock(return_value=httpx.Response(200, content=b"WEBVTT\n\n"))

        read = await reader.teams_read_transcript(
            client,
            handle=TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID),
            offset=0,
            limit=200,
        )

        assert read.turns == []
        assert read.next_offset is None

    async def test_a_limit_above_the_ceiling_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await reader.teams_read_transcript(
                client,
                handle=TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID),
                offset=0,
                limit=reader.MAX_TURNS + 1,
            )


class TestNarrowingWhatComesBack:
    async def test_a_lower_bound_keeps_everything_still_running_at_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _spoken(graph)

        read = await reader.teams_read_transcript(
            client, handle=_transcript(), offset=0, limit=200, from_seconds=1.0
        )

        assert [turn.text for turn in read.turns] == [
            "Sorry, joining late & muted.",
            "We should raise the floor price by three per cent.",
            "Agreed <that> works.",
            "Nobody was attributed for this one.",
        ], "the first turn started at -2.5 and was still running at 1.0"
        assert read.turns[0].start_seconds == -2.5

    async def test_a_lower_bound_drops_what_had_finished_before_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _spoken(graph)

        read = await reader.teams_read_transcript(
            client, handle=_transcript(), offset=0, limit=200, from_seconds=16.0
        )

        assert [turn.speaker for turn in read.turns] == ["Grace Hopper", "Ada Lovelace", None]
        assert read.next_offset is None

    async def test_an_upper_bound_keeps_the_turn_that_starts_exactly_on_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _spoken(graph)

        read = await reader.teams_read_transcript(
            client, handle=_transcript(), offset=0, limit=200, to_seconds=62.0
        )

        assert [turn.start_seconds for turn in read.turns] == [-2.5, 16.246, 62.0]

    async def test_both_bounds_together_cut_a_window_out_of_the_middle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _spoken(graph)

        read = await reader.teams_read_transcript(
            client, handle=_transcript(), offset=0, limit=200, from_seconds=20.0, to_seconds=64.0
        )

        assert [turn.text for turn in read.turns] == ["Agreed <that> works."]

    async def test_a_speaker_filter_keeps_only_that_speakers_turns(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _spoken(graph)

        read = await reader.teams_read_transcript(
            client, handle=_transcript(), offset=0, limit=200, speaker="Ada Lovelace"
        )

        assert [turn.text for turn in read.turns] == [
            "Sorry, joining late & muted.",
            "Agreed <that> works.",
        ]
        assert read.speaker_attribution is True

    @pytest.mark.parametrize(
        "speaker",
        [
            "ada",
            "ADA LOVELACE",
            "lovelace",
            "Lovelace",
            " ada ",
            "\tlovelace\n",
            "  Ada Lovelace  ",
        ],
        ids=["given", "shouted", "sur", "cased", "padded-given", "tabbed-sur", "padded-full"],
    )
    async def test_a_speaker_is_matched_case_insensitively_and_by_part_of_the_name(
        self, client: GraphServiceClient, graph: respx.MockRouter, speaker: str
    ) -> None:
        """A copied name carries the whitespace around it, and a turn's own speaker is stripped at
        parse time, so the filter is stripped too."""
        _spoken(graph)

        read = await reader.teams_read_transcript(
            client, handle=_transcript(), offset=0, limit=200, speaker=speaker
        )

        assert [turn.speaker for turn in read.turns] == ["Ada Lovelace", "Ada Lovelace"]

    async def test_an_entity_in_a_speaker_name_is_unescaped_like_the_words(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """WebVTT escapes `&` inside a cue payload, so a display name holding one arrives
        encoded, and a filter written from the reported name would then match nothing."""
        graph.get(_CONTENT).mock(
            return_value=httpx.Response(
                200,
                content=(
                    b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
                    b"<v Ada &amp; Charles>Both of us &amp; nobody else.</v>\n"
                ),
            )
        )

        read = await reader.teams_read_transcript(
            client, handle=_transcript(), offset=0, limit=200, speaker="ada & charles"
        )

        assert [(turn.speaker, turn.text) for turn in read.turns] == [
            ("Ada & Charles", "Both of us & nobody else.")
        ]

    async def test_a_speaker_and_a_window_narrow_together(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _spoken(graph)

        read = await reader.teams_read_transcript(
            client,
            handle=_transcript(),
            offset=0,
            limit=200,
            from_seconds=10.0,
            to_seconds=100.0,
            speaker="ada",
        )

        assert [turn.text for turn in read.turns] == ["Agreed <that> works."]

    async def test_a_page_is_cut_from_what_survived_the_filter(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A `next_offset` over the whole transcript would page for turns that cannot come."""
        _spoken(graph)

        read = await reader.teams_read_transcript(
            client, handle=_transcript(), offset=0, limit=2, speaker="ada"
        )

        assert [turn.text for turn in read.turns] == [
            "Sorry, joining late & muted.",
            "Agreed <that> works.",
        ]
        assert read.next_offset is None, "two matched, two returned; the other turns are not more"

    async def test_the_next_offset_of_a_filtered_page_continues_the_filtered_sequence(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Offset 2 of this transcript is Ada's second turn; offset 2 of what `from_seconds=2.0`
        matched is the unattributed one."""
        _spoken(graph)
        handle = _transcript()

        first = await reader.teams_read_transcript(
            client, handle=handle, offset=0, limit=2, from_seconds=2.0
        )
        second = await reader.teams_read_transcript(
            client, handle=handle, offset=first.next_offset or 0, limit=2, from_seconds=2.0
        )

        assert first.next_offset == 2
        assert [turn.speaker for turn in first.turns] == ["Grace Hopper", "Ada Lovelace"]
        assert [turn.text for turn in second.turns] == ["Nobody was attributed for this one."]
        assert second.next_offset is None

    async def test_a_window_nothing_falls_in_is_no_turns_rather_than_a_refusal(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _spoken(graph)

        read = await reader.teams_read_transcript(
            client, handle=_transcript(), offset=0, limit=200, from_seconds=7200.0
        )

        assert read.turns == []
        assert read.next_offset is None

    async def test_a_speaker_filter_in_a_tenant_with_no_speakers_matches_nothing_and_says_why(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Where the tenant forbids attribution every `speaker` is null, so the filter matches
        nothing legitimately and only `speaker_attribution` says why."""
        _spoken_by_nobody(graph)

        read = await reader.teams_read_transcript(
            client, handle=_transcript(), offset=0, limit=200, speaker="ada"
        )

        assert read.turns == []
        assert read.speaker_attribution is False, "the reason the page is empty"
        assert read.next_offset is None

    async def test_time_still_filters_where_the_speakers_are_gone(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _spoken_by_nobody(graph)

        read = await reader.teams_read_transcript(
            client, handle=_transcript(), offset=0, limit=200, from_seconds=30.0
        )

        assert [turn.start_seconds for turn in read.turns] == [62.0]

    async def test_filters_left_unset_return_the_whole_transcript(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _spoken(graph)

        read = await reader.teams_read_transcript(
            client,
            handle=_transcript(),
            offset=0,
            limit=200,
            from_seconds=None,
            to_seconds=None,
            speaker=None,
        )

        assert [turn.speaker for turn in read.turns] == [
            "Ada Lovelace",
            "Grace Hopper",
            "Ada Lovelace",
            None,
        ]
        assert read.next_offset is None

    async def test_a_window_that_ends_before_it_starts_is_a_programming_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        content = _spoken(graph)

        with pytest.raises(AssertionError):
            _ = await reader.teams_read_transcript(
                client,
                handle=_transcript(),
                offset=0,
                limit=200,
                from_seconds=60.0,
                to_seconds=30.0,
            )

        assert not content.called, "an impossible window costs no Graph request"
