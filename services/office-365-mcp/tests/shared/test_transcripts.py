"""`shared/transcripts.py`: cue parsing, independent of either reader."""

from pathlib import Path

from office_365_mcp.shared import transcripts
from office_365_mcp.shared.transcripts import TranscriptTurn

_VTT = """\
WEBVTT

-00:00:02.500 --> 00:00:01.250
<v Ada Lovelace>Sorry, joining late &amp; muted.</v>

00:00:16.246 --> 00:00:19.900
<v.loud Grace Hopper>We should <i>raise</i> the floor price.</v>

01:00:03.000 --> 01:00:04.000
<v Ada Lovelace></v>
"""


class TestTheParser:
    def test_a_cue_block_becomes_a_turn_with_the_markup_removed(self, tmp_path: Path) -> None:
        path = tmp_path / "transcript.vtt"
        path.write_text(_VTT, encoding="utf-8")
        window = transcripts._Window(  # pyright: ignore[reportPrivateUsage]
            offset=0, limit=10, from_seconds=None, to_seconds=None, speaker=None
        )

        turns, next_offset = transcripts._page(  # pyright: ignore[reportPrivateUsage]
            path, attributed=True, window=window
        )

        parsed = [(turn.speaker, turn.start_seconds, turn.end_seconds, turn.text) for turn in turns]

        assert parsed == [
            ("Ada Lovelace", -2.5, 1.25, "Sorry, joining late & muted."),
            ("Grace Hopper", 16.246, 19.9, "We should raise the floor price."),
        ]
        assert next_offset is None, "an empty voice cue is not a turn, and not a next page"

    def test_the_start_names_no_listing_tool(self) -> None:
        description = TranscriptTurn.model_fields["start_seconds"].description or ""

        assert "teams_list_meeting_transcripts" not in description
