import httpx
import pytest
import respx
from kiota_abstractions.method import Method
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.identity import Identity
from msgraph.generated.models.identity_set import IdentitySet
from msgraph.generated.models.item_reference import ItemReference
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphNotFound, request_with_query
from office_365_mcp.shared.files import (
    FAIL_ON_CONFLICT,
    ITEM_FIELDS,
    NAME_RULES,
    DriveItemSummary,
    item_for_a_question,
    unusable_name,
)

_DRIVE_ID = "b!SYNTHETICDRIVE0001"
_FOLDER_ID = "01SYNTHETICFOLDER0001"

_FOLDER_PATH = "/drives/b%21SYNTHETICDRIVE0001/items/01SYNTHETICFOLDER0001"

_RESERVED = '"*:<>?/\\|'


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


class TestUnusableName:
    @pytest.mark.parametrize("character", list(_RESERVED))
    def test_a_reserved_character_is_refused_and_named(self, character: str) -> None:
        refusal = unusable_name(f"Q1{character}Q2")

        assert refusal is not None
        assert f"The name contains `{character}`." in refusal

    def test_the_refusal_lists_every_reserved_character_in_order(self) -> None:
        refusal = unusable_name("Q1/Q2")

        assert refusal is not None
        assert '`"` `*` `:` `<` `>` `?` `/` `\\` `|`' in refusal

    def test_the_name_rules_list_every_reserved_character_and_the_reserved_start(self) -> None:
        assert '" * : < > ? / \\ |.' in NAME_RULES
        assert "It must not start with `~$`." in NAME_RULES

    def test_a_name_that_starts_with_a_tilde_and_a_dollar_sign_is_refused(self) -> None:
        refusal = unusable_name("~$draft.docx")

        assert refusal is not None
        assert "The name starts with `~$`." in refusal

    @pytest.mark.parametrize("name", ["~draft", "Q3 #1", "50%", "Reports."])
    def test_hash_percent_a_lone_tilde_and_a_trailing_period_are_usable(self, name: str) -> None:
        assert unusable_name(name) is None

    @pytest.mark.parametrize("name", ["", " ", "\t\n"])
    def test_a_blank_name_is_refused(self, name: str) -> None:
        refusal = unusable_name(name)

        assert refusal is not None
        assert "The name is empty or has only spaces in it." in refusal

    @pytest.mark.parametrize(
        "name",
        [
            "Quarterly report 2026.docx",
            "Überprüfung März",
            "日本語のメモ.txt",
            "draft~1.docx",
            "v1.2 notes",
        ],
    )
    def test_spaces_non_ascii_letters_and_inner_marks_are_usable(self, name: str) -> None:
        assert unusable_name(name) is None

    def test_one_refusal_names_every_problem(self) -> None:
        refusal = unusable_name('~$Q1/Q2"3')

        assert refusal is not None
        assert 'The name contains `/` and `"`.' in refusal
        assert "The name starts with `~$`." in refusal

    @pytest.mark.parametrize("name", ["Q1|Q2", "~$Q1", "   "])
    def test_a_refusal_says_that_nothing_changed_and_not_to_retry(self, name: str) -> None:
        refusal = unusable_name(name)

        assert refusal is not None
        assert refusal.startswith(
            "Nothing was changed, because Microsoft does not allow this name in OneDrive and "
            + "SharePoint."
        )
        assert refusal.endswith("This same value fails again, so do not retry it.")
        assert "do not accept" not in refusal


class TestItemForAQuestion:
    async def test_it_reads_the_item_by_its_drive_and_selects_the_root_facet(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_FOLDER_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": _FOLDER_ID,
                    "name": "Reports",
                    "folder": {"childCount": 2},
                    "root": {},
                    "parentReference": {"driveId": _DRIVE_ID},
                },
            )
        )

        item = await item_for_a_question(client, _DRIVE_ID, _FOLDER_ID)

        assert item.id == _FOLDER_ID
        assert item.root is not None
        selected = route.calls.last.request.url.params["$select"].split(",")
        assert selected == [*ITEM_FIELDS, "root"]

    async def test_a_404_propagates(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_FOLDER_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await item_for_a_question(client, _DRIVE_ID, _FOLDER_ID)


class TestFailOnConflict:
    async def test_the_conflict_behavior_reaches_the_url_of_a_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(f"{_FOLDER_PATH}/children").mock(
            return_value=httpx.Response(
                201, json={"id": "01SYNTHETICNEW0001", "name": "Q3", "folder": {"childCount": 0}}
            )
        )
        children = client.drives.by_drive_id(_DRIVE_ID).items.by_drive_item_id(_FOLDER_ID).children
        request = request_with_query(
            Method.POST,
            children.url_template,
            children.path_parameters,
            query=FAIL_ON_CONFLICT,
        )
        request.headers.try_add("Accept", "application/json")
        request.set_stream_content(b'{"name": "Q3", "folder": {}}', "application/json")

        created = await client.request_adapter.send_async(  # pyright: ignore[reportUnknownMemberType]
            request, DriveItem, {"XXX": ODataError}
        )

        assert isinstance(created, DriveItem)
        assert created.id == "01SYNTHETICNEW0001"
        assert route.calls.last.request.url.params["@microsoft.graph.conflictBehavior"] == "fail"
