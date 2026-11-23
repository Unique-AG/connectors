"""A call transcript handle is not a meeting handle, and the reverse."""

import pytest

from office_365_mcp.shared import handles
from tests.tools.conftest import JOIN_WEB_URL, MEETING_ID

_TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0001"


class TestTheCallTranscriptHandleGrammar:
    def test_a_call_transcript_handle_round_trips_both_ids(self) -> None:
        handle = handles.CallTranscriptHandle("MSo1N2Y5:ZGFjYw==", "MSMjMCMj/0001")

        parsed = handles.call_transcript_handle(handle.uri)

        assert parsed is not None
        assert (parsed.call_id, parsed.transcript_id) == (
            "MSo1N2Y5:ZGFjYw==",
            "MSMjMCMj/0001",
        )

    @pytest.mark.parametrize(
        "uri",
        [
            handles.MeetingHandle(JOIN_WEB_URL).uri,
            handles.TranscriptHandle(MEETING_ID, _TRANSCRIPT_ID).uri,
            "teams:///calltranscripts/only-one-id",
            "teams:///calltranscripts//a",
            "teams:///calltranscripts/a/%20",
            "teams:///calltranscripts/a/b/c",
            "",
        ],
    )
    def test_what_is_not_a_call_transcript_handle(self, uri: str) -> None:
        assert handles.call_transcript_handle(uri) is None

    def test_a_call_transcript_uri_is_not_a_meeting_transcript_handle(self) -> None:
        uri = handles.CallTranscriptHandle("call-1", _TRANSCRIPT_ID).uri

        assert handles.transcript_handle(uri) is None
