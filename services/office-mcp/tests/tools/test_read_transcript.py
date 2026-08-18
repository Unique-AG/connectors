"""`read_transcript`: the words that come back, and what narrows them.

Every payload is synthesised. A transcript is the most sensitive thing this connector touches, so
nothing here came from a meeting: the speakers are historical figures, the words are invented, and
the ids are obviously fake.
"""

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import GraphForbidden
from office_mcp.shared import identity
from office_mcp.shared.handles import TranscriptHandle
from office_mcp.tools import read_transcript as reader

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

# A synthetic WebVTT transcript in the shape Graph's `/content` returns, exercising everything the
# parser has to survive: the header, a NOTE block, cue identifier lines, a voice tag with a class,
# a cue wrapped over two lines, escaped entities, inline markup, a cue nobody was attributed for,
# and the negative offset Microsoft documents for transcription that started mid-conversation.
# Nothing anybody said: the speakers are long dead and the words are invented.
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

# The same transcript as the unattributed format returns it: cue timings, no voice tags at all.
TRANSCRIPT_UNATTRIBUTED = """00:00:16.246 --> 00:00:19.900
We should raise the floor price by three per cent.

00:01:02.000 --> 00:01:04.500
Agreed that works.
"""


def _transcript() -> TranscriptHandle:
    """The handle `list_meeting_transcripts` would have minted for the transcript below."""
    return TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID)


def _spoken(graph: respx.MockRouter) -> respx.Route:
    """The words, answered to every read: `/content` is one stream and each call fetches it all."""
    return graph.get(_CONTENT).mock(
        return_value=httpx.Response(200, content=TRANSCRIPT_VTT.encode())
    )


def _spoken_by_nobody(graph: respx.MockRouter) -> respx.Route:
    """The same endpoint in a tenant with speaker attribution off, which is where it is decided.

    The attributed format is refused and the plain one served, exactly as Graph does it — serving
    unattributed bytes to the attributed request would say `speaker_attribution` is true, which is
    the field a caller reads to find out why a speaker filter matched nothing.
    """

    def respond(request: httpx.Request) -> httpx.Response:
        if request.headers["accept"] == "text/vtt":
            return httpx.Response(403, json=_ATTRIBUTION_OFF)
        return httpx.Response(200, content=TRANSCRIPT_UNATTRIBUTED.encode())

    return graph.get(_CONTENT).mock(side_effect=respond)


class TestReadingTheWords:
    async def test_vtt_becomes_speaker_attributed_timestamped_turns(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The whole differentiator, and every parsing trap in one transcript: the `WEBVTT` header,
        a `NOTE` block, cue identifier lines, a voice tag with a class, a cue wrapped over two
        lines, HTML entities, inline markup, an unattributed cue, an empty one, and the negative
        offset Microsoft documents for transcription that started mid-conversation."""
        route = graph.get(_CONTENT).mock(
            return_value=httpx.Response(
                200, content=TRANSCRIPT_VTT.encode(), headers={"content-type": "text/vtt"}
            )
        )

        read = await reader.read_transcript(
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

        first = await reader.read_transcript(client, handle=handle, offset=0, limit=2)
        second = await reader.read_transcript(
            client, handle=handle, offset=first.next_offset or 0, limit=2
        )

        assert first.next_offset == 2, "the offset is the whole of 'there are more turns'"
        assert [turn.speaker for turn in first.turns] == ["Ada Lovelace", "Grace Hopper"]
        assert second.next_offset is None, "and null on the last page is the whole of saying so"
        assert [turn.speaker for turn in second.turns] == ["Ada Lovelace", None]

    async def test_a_tenant_that_forbids_speaker_names_degrades_instead_of_failing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph's own documented remedy: ask again for the unattributed format, which succeeds.
        `services/teams-mcp` hardcodes `Accept: text/vtt` and so loses the transcript entirely in
        such a tenant."""
        attempts: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            accept = request.headers["accept"]
            attempts.append(accept)
            if accept == "text/vtt":
                return httpx.Response(403, json=_ATTRIBUTION_OFF)
            return httpx.Response(200, content=TRANSCRIPT_UNATTRIBUTED.encode())

        graph.get(_CONTENT).mock(side_effect=respond)

        read = await reader.read_transcript(
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
        """The other 403 on the same endpoint. Microsoft says there is no request-side workaround,
        so a second request would be a wasted call and the advice for it names an administrator
        rather than a format — which means the retry must be scoped to the inner code, not to 403.
        """
        route = graph.get(_CONTENT).mock(return_value=httpx.Response(403, json=_TENANT_SWITCH_OFF))

        with pytest.raises(GraphForbidden) as raised:
            _ = await reader.read_transcript(
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
        """The claim `_accepting` is written on, checked rather than believed. kiota's
        `RequestConfiguration.headers` defaults to ONE `HeadersCollection` shared by every
        configuration in the process — two configurations built here are the same object — so an
        `Accept` added to the default is added to every Graph call this connector goes on to make,
        and the generated builders' own `try_add("Accept", "application/json")` is then a no-op that
        cannot take it back. `Accept: text/vtt` on a JSON call is not a header nobody reads: it is
        every other tool answering with a deserialisation failure, from a request this one made.

        The unrelated call is `shared/identity.py`'s `GET /me`, and what makes it a witness rather
        than a passenger is that it passes a `RequestConfiguration` of its own — a call passing none
        would send Graph's default `Accept` whether or not this one had polluted the shared object,
        so it would keep passing while the leak came back.
        """
        _spoken(graph)
        profile = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))

        _ = await reader.read_transcript(client, handle=_transcript(), offset=0, limit=200)
        _ = await identity.signed_in_user(client)

        assert "text/vtt" not in profile.calls.last.request.headers["accept"]

    async def test_an_empty_transcript_is_no_turns_rather_than_a_blank_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_CONTENT).mock(return_value=httpx.Response(200, content=b"WEBVTT\n\n"))

        read = await reader.read_transcript(
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
            _ = await reader.read_transcript(
                client,
                handle=TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID),
                offset=0,
                limit=reader.MAX_TURNS + 1,
            )


class TestNarrowingWhatComesBack:
    """The filters, over the one transcript that carries every shape the parser survives.

    An hour of meeting is thousands of turns and a model reads it to answer one question, so the
    narrowing has to happen here rather than in the model's context. What is asserted is the part a
    caller cannot check for itself: which turns a bound admits, and that the page and its
    `next_offset` are counted over what survived the filter rather than over the whole transcript.
    """

    async def test_a_lower_bound_keeps_everything_still_running_at_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Overlap and not containment: the turn that was mid-sentence when the clock struck is the
        one a caller asking "from here" most wants, and dropping it would silently cut the sentence
        their question is about."""
        _spoken(graph)

        read = await reader.read_transcript(
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

        read = await reader.read_transcript(
            client, handle=_transcript(), offset=0, limit=200, from_seconds=16.0
        )

        assert [turn.speaker for turn in read.turns] == ["Grace Hopper", "Ada Lovelace", None]
        assert read.next_offset is None

    async def test_an_upper_bound_keeps_the_turn_that_starts_exactly_on_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Inclusive at both ends, for the same reason: a bound a caller read off a previous answer
        names a turn that exists, and excluding it would make the two ends disagree."""
        _spoken(graph)

        read = await reader.read_transcript(
            client, handle=_transcript(), offset=0, limit=200, to_seconds=62.0
        )

        assert [turn.start_seconds for turn in read.turns] == [-2.5, 16.246, 62.0]

    async def test_both_bounds_together_cut_a_window_out_of_the_middle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _spoken(graph)

        read = await reader.read_transcript(
            client, handle=_transcript(), offset=0, limit=200, from_seconds=20.0, to_seconds=64.0
        )

        assert [turn.text for turn in read.turns] == ["Agreed <that> works."]

    async def test_a_speaker_filter_keeps_only_that_speakers_turns(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _spoken(graph)

        read = await reader.read_transcript(
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
        """A model writes the name it read in a previous answer, or the half of it the caller said.
        An exact, case-sensitive match would answer "nobody said that" to a question about somebody
        who spoke — a wrong answer with the shape of a right one. A copied name carries the
        whitespace around it, and the turn's own speaker is stripped at parse time, so the filter is
        stripped as well."""
        _spoken(graph)

        read = await reader.read_transcript(
            client, handle=_transcript(), offset=0, limit=200, speaker=speaker
        )

        assert [turn.speaker for turn in read.turns] == ["Ada Lovelace", "Ada Lovelace"]

    async def test_an_entity_in_a_speaker_name_is_unescaped_like_the_words(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """WebVTT escapes `&` inside a cue payload, so a display name that holds one arrives
        encoded. The name is what a model reports and what `speaker` matches against, so it is
        unescaped exactly as the words are. Left encoded, a filter written from the reported name
        would answer "nobody said that" about somebody who spoke."""
        graph.get(_CONTENT).mock(
            return_value=httpx.Response(
                200,
                content=(
                    b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n"
                    b"<v Ada &amp; Charles>Both of us &amp; nobody else.</v>\n"
                ),
            )
        )

        read = await reader.read_transcript(
            client, handle=_transcript(), offset=0, limit=200, speaker="ada & charles"
        )

        assert [(turn.speaker, turn.text) for turn in read.turns] == [
            ("Ada & Charles", "Both of us & nobody else.")
        ]

    async def test_a_speaker_and_a_window_narrow_together(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """All three at once, which is the question this exists for: what did she say in that
        stretch. Each filter has to hold, not the last one written."""
        _spoken(graph)

        read = await reader.read_transcript(
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
        """A `next_offset` counted over the whole transcript would offer more where the filter
        already returned everything it matched, and a model would page for turns that cannot come.
        """
        _spoken(graph)

        read = await reader.read_transcript(
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
        """The offset a caller sends back has to index the same sequence it was cut from. Counted
        over the unfiltered turns it would land in the middle of them: offset 2 of this transcript
        is Ada's second turn, and offset 2 of what `from_seconds=2.0` matched is the unattributed
        one."""
        _spoken(graph)
        handle = _transcript()

        first = await reader.read_transcript(
            client, handle=handle, offset=0, limit=2, from_seconds=2.0
        )
        second = await reader.read_transcript(
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

        read = await reader.read_transcript(
            client, handle=_transcript(), offset=0, limit=200, from_seconds=7200.0
        )

        assert read.turns == []
        assert read.next_offset is None

    async def test_a_speaker_filter_in_a_tenant_with_no_speakers_matches_nothing_and_says_why(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The one empty answer that must not read as "she never spoke". Where the tenant forbids
        attribution every `speaker` is null, so the filter legitimately matches nothing — and
        `speaker_attribution` false is the field that explains it. Refusing the call instead would
        deny a filter the transcript itself supports for time."""
        _spoken_by_nobody(graph)

        read = await reader.read_transcript(
            client, handle=_transcript(), offset=0, limit=200, speaker="ada"
        )

        assert read.turns == []
        assert read.speaker_attribution is False, "the reason the page is empty"
        assert read.next_offset is None

    async def test_time_still_filters_where_the_speakers_are_gone(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _spoken_by_nobody(graph)

        read = await reader.read_transcript(
            client, handle=_transcript(), offset=0, limit=200, from_seconds=30.0
        )

        assert [turn.start_seconds for turn in read.turns] == [62.0]

    async def test_filters_left_unset_return_the_whole_transcript(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The default is the answer this tool gave before the filters existed, and passing the
        absent value explicitly is what a model does when it has nothing to narrow by."""
        _spoken(graph)

        read = await reader.read_transcript(
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
        """No transcript can satisfy it, so it is a mistake in the caller rather than an empty
        answer — and the tool layer refuses it before this is ever reached."""
        content = _spoken(graph)

        with pytest.raises(AssertionError):
            _ = await reader.read_transcript(
                client,
                handle=_transcript(),
                offset=0,
                limit=200,
                from_seconds=60.0,
                to_seconds=30.0,
            )

        assert not content.called, "an impossible window costs no Graph request"
