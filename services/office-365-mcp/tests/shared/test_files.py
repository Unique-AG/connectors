from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.identity import Identity
from msgraph.generated.models.identity_set import IdentitySet
from msgraph.generated.models.item_reference import ItemReference

from office_365_mcp.shared.files import ITEM_FIELDS, DriveItemSummary

_DRIVE_ID = "b!SYNTHETICDRIVE0001"


def _item(created_by: IdentitySet | None) -> DriveItem:
    return DriveItem(
        id="01SYNTHETICITEM0001",
        name="Budget 2026.xlsx",
        parent_reference=ItemReference(drive_id=_DRIVE_ID),
        created_by=created_by,
    )


def _summary(created_by: IdentitySet | None) -> DriveItemSummary:
    summary = DriveItemSummary.from_item(_item(created_by))
    assert summary is not None
    return summary


class TestDriveItemSummaryCreatedBy:
    def test_it_asks_graph_for_the_creator(self) -> None:
        assert "createdBy" in ITEM_FIELDS

    def test_it_maps_a_user_to_their_display_name(self) -> None:
        summary = _summary(IdentitySet(user=Identity(display_name="Ada Lovelace")))

        assert summary.created_by == "Ada Lovelace"

    def test_it_gives_none_when_only_an_application_created_the_item(self) -> None:
        summary = _summary(IdentitySet(application=Identity(display_name="Synthetic Sync App")))

        assert summary.created_by is None

    def test_it_gives_none_when_graph_sent_no_creator(self) -> None:
        summary = _summary(None)

        assert summary.created_by is None
