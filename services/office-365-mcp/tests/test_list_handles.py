import pytest

from office_365_mcp.shared.handles import (
    DriveFileHandle,
    ListHandle,
    ListItemHandle,
    list_handle,
    list_item_handle,
)

SITE_ID = "contoso.sharepoint.com,11111111-aaaa-bbbb-cccc-222222222222,33333333-dddd-eeee-ffff-4444"
LIST_ID = "55555555-6666-7777-8888-999999999999"
ITEM_ID = "42"

LIST_URI = ListHandle(SITE_ID, LIST_ID).uri
LIST_ITEM_URI = ListItemHandle(SITE_ID, LIST_ID, ITEM_ID).uri
FILE_URI = DriveFileHandle("b!drive", "item").uri


class TestListHandle:
    def test_round_trips_a_composite_site_id(self) -> None:
        assert "," not in LIST_URI
        assert list_handle(LIST_URI) == ListHandle(SITE_ID, LIST_ID)

    @pytest.mark.parametrize(
        "uri",
        [
            LIST_ITEM_URI,
            FILE_URI,
            "sharepoint:///lists/%20/" + LIST_ID,
            "sharepoint:///lists/site/%20",
        ],
    )
    def test_returns_none_for_another_shape_or_a_blank_segment(self, uri: str) -> None:
        assert list_handle(uri) is None


class TestListItemHandle:
    def test_round_trips_a_composite_site_id(self) -> None:
        assert "," not in LIST_ITEM_URI
        assert list_item_handle(LIST_ITEM_URI) == ListItemHandle(SITE_ID, LIST_ID, ITEM_ID)

    def test_item_id_survives_an_encoded_character(self) -> None:
        handle = ListItemHandle(SITE_ID, LIST_ID, "b!1/2")

        assert "!" not in handle.uri
        assert list_item_handle(handle.uri) == handle

    @pytest.mark.parametrize(
        "uri",
        [
            LIST_URI,
            FILE_URI,
            f"sharepoint:///listitems/site/{LIST_ID}/%20",
        ],
    )
    def test_returns_none_for_another_shape_or_a_blank_segment(self, uri: str) -> None:
        assert list_item_handle(uri) is None
