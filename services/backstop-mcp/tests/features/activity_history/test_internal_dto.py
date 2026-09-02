import pytest
from fastmcp.exceptions import ToolError

from backstop_mcp.features.activity_history import ResourceIdentifierDto


class TestResourceIdentifierFromActivityId:
    def test_splits_a_history_composite_handle(self) -> None:
        handle = ResourceIdentifierDto.from_activity_id("meeting-or-calls_76537547")

        assert handle.resource_type == "meeting-or-calls"
        assert handle.resource_id == "76537547"
        assert handle.is_meeting_or_call is True

    @pytest.mark.parametrize("activity_id", ["1659094659", "1791831538"])
    def test_accepts_a_search_row_id(self, activity_id: str) -> None:
        handle = ResourceIdentifierDto.from_activity_id(activity_id)

        assert handle.resource_type is None
        assert handle.resource_id == activity_id
        assert handle.is_meeting_or_call is False

    def test_rejects_an_empty_handle(self) -> None:
        with pytest.raises(ToolError, match="not a valid activity_id"):
            ResourceIdentifierDto.from_activity_id("  ")

    @pytest.mark.parametrize("activity_id", ["email_42", "emails_99"])
    def test_rejects_a_history_email_handle(self, activity_id: str) -> None:
        with pytest.raises(ToolError, match="email handle"):
            ResourceIdentifierDto.from_activity_id(activity_id)
