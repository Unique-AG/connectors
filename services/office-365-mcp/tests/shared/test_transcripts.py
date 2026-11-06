"""`shared/transcripts.py`: the turn fields. Cue parsing is covered through the readers."""

from office_365_mcp.shared.transcripts import TranscriptTurn


class TestTheParser:
    def test_the_start_names_no_listing_tool(self) -> None:
        description = TranscriptTurn.model_fields["start_seconds"].description or ""

        assert "teams_list_meeting_transcripts" not in description
