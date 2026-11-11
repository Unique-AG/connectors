import pytest
import respx
from fastmcp.exceptions import ToolError

from tests.integration.support import call

BLANK = "%20"


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("outlook_read_event", {"uri": f"outlook:///events/{BLANK}/event"}),
        ("outlook_read_event", {"uri": f"outlook:///events/calendar/{BLANK}"}),
        ("outlook_read_event_attachment", {"uri": "outlook:///events/calendar/event"}),
        (
            "outlook_read_event_attachment",
            {"uri": f"outlook:///events/calendar/event/attachments/{BLANK}"},
        ),
        ("sharepoint_read_file", {"file": f"sharepoint:///files/{BLANK}/item"}),
        ("sharepoint_read_file", {"file": f"sharepoint:///files/drive/{BLANK}"}),
        ("onenote_delete_page", {"page": f"onenote:///groups/{BLANK}/pages/page"}),
        ("onenote_delete_page", {"page": f"onenote:///pages/{BLANK}"}),
        ("teams_read_message", {"uri": f"teams:///chats/{BLANK}/messages/1"}),
        ("teams_read_transcript", {"uri": f"teams:///transcripts/meeting/{BLANK}"}),
        ("teams_read_transcript", {"uri": f"teams:///transcripts/{BLANK}/transcript"}),
        ("teams_read_meeting", {"meeting_uri": f"teams:///meetings/{BLANK}"}),
    ],
    ids=[
        "event without a calendar",
        "event without an id",
        "attachment of two ids",
        "attachment without an id",
        "file without a drive",
        "file without an item",
        "page of a group without an id",
        "page without an id",
        "chat message without a chat",
        "transcript without an id",
        "transcript without a meeting",
        "meeting without a join address",
    ],
)
async def test_a_reference_whose_id_is_blank_is_refused_and_asks_microsoft_nothing(
    graph: respx.MockRouter, tool: str, arguments: dict[str, str]
) -> None:
    with pytest.raises(ToolError) as raised:
        _ = await call(tool, person=None, **arguments)

    assert "handle" in str(raised.value)
    assert not graph.calls
