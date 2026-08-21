import pytest
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from backstop_mcp.features.activity_history import (
    ActivityAttributes,
    ActivityItemDto,
    ActivityPageDto,
    ResourceIdentifierDto,
)


class TestActivityItemFromAttributes:
    def test_unknown_properties_are_ignored(self) -> None:
        item = ActivityItemDto.from_attributes(
            "meeting-or-calls_1",
            "meeting",
            ActivityAttributes.model_validate(
                {"title": "Q1", "tenantExtra": "dropped", "another": 1}
            ),
        )

        assert item.title == "Q1"
        assert not hasattr(item, "tenantExtra")

    def test_absent_fields_default_to_none(self) -> None:
        item = ActivityItemDto.from_attributes(
            "meeting-or-calls_1",
            "meeting",
            ActivityAttributes.model_validate({}),
        )

        assert item.title is None

    def test_malformed_timestamp_becomes_none(self) -> None:
        item = ActivityItemDto.from_attributes(
            "meeting-or-calls_1",
            "meeting",
            ActivityAttributes.model_validate({"createdTimestamp": "not-a-datetime"}),
        )

        assert item.created_timestamp is None


class TestActivityItemDto:
    def test_id_is_required(self) -> None:
        with pytest.raises(ValidationError):
            ActivityItemDto.model_validate({"stream": "meeting"})

    def test_stream_is_required(self) -> None:
        with pytest.raises(ValidationError):
            ActivityItemDto.model_validate({"id": "meeting-or-calls_1"})

    def test_absent_optional_fields_default_to_none(self) -> None:
        item = ActivityItemDto.model_validate({"id": "meeting-or-calls_1", "stream": "meeting"})

        assert item.title is None
        assert item.effective_date is None


class TestActivityPageDto:
    def test_end_of_stream_is_required(self) -> None:
        with pytest.raises(ValidationError):
            ActivityPageDto.model_validate({"items": []})

    def test_items_default_to_empty(self) -> None:
        page = ActivityPageDto.model_validate({"end_of_stream": True})

        assert page.items == ()
        assert page.end_of_stream is True


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
