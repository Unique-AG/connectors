import ast
import pathlib
import re

import httpx
import pytest
import respx
from kiota_abstractions.method import Method
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.folder import Folder
from msgraph.generated.models.identity import Identity
from msgraph.generated.models.identity_set import IdentitySet
from msgraph.generated.models.item_reference import ItemReference
from msgraph.generated.models.root import Root
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphNotFound, request_with_query, send_parsed
from office_365_mcp.shared.files import (
    FAIL_ON_CONFLICT,
    FOLDER_HANDLE_SOURCES,
    ITEM_FIELDS,
    ITEM_HANDLE_SOURCES,
    NAME_RULES,
    TOP_FOLDER_LABEL,
    UNNAMED_FOLDER_LABEL,
    UNNAMED_ITEM_LABEL,
    DriveItemSummary,
    folder_label,
    item_access_refused,
    item_for_a_question,
    item_label,
    parent_folder_label,
    summary_after_write,
    unusable_name,
)
from office_365_mcp.shared.handles import DriveFileHandle
from office_365_mcp.shared.prose import PREVIEW_CHARACTERS
from office_365_mcp.shared.seam import Advised

_SRC = pathlib.Path(__file__).parent.parent.parent / "src" / "office_365_mcp"
_OWNER = _SRC / "shared" / "files.py"
_SHAREPOINT_TOOLS = sorted((_SRC / "tools").glob("sharepoint_*.py"))

_LABELS = frozenset({TOP_FOLDER_LABEL, UNNAMED_FOLDER_LABEL, UNNAMED_ITEM_LABEL})
_RETIRED_LABELS = frozenset(
    {
        "the top folder of its drive",
        "the top of the drive",
        "the top folder of a drive",
        "an item with no name",
        "its folder",
    }
)

_DRIVE_ID = "b!SYNTHETICDRIVE0001"
_FOLDER_ID = "01SYNTHETICFOLDER0001"
_ITEM_ID = "01SYNTHETICITEM0001"

_FOLDER_PATH = "/drives/b%21SYNTHETICDRIVE0001/items/01SYNTHETICFOLDER0001"
_ITEM_PATH = "/drives/b%21SYNTHETICDRIVE0001/items/01SYNTHETICITEM0001"

_UNREAD = "Microsoft 365 made the synthetic change. Then this connector did not receive the item."

_RESERVED = '"*:<>?/\\|'


def _item(created_by: IdentitySet | None) -> DriveItem:
    return DriveItem(
        id=_ITEM_ID,
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


def _reread_payload(*, with_drive: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {"id": _ITEM_ID, "name": "Budget 2026.xlsx", "file": {}}
    if with_drive:
        payload["parentReference"] = {"driveId": _DRIVE_ID, "id": _FOLDER_ID}
    return payload


class TestSummaryAfterWrite:
    async def test_an_answer_with_a_drive_is_the_summary_and_is_not_read_again(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reread = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_reread_payload())
        )

        summary = await summary_after_write(
            client, _DRIVE_ID, _item(None), item_id=_ITEM_ID, unread=_UNREAD
        )

        assert summary.uri == DriveFileHandle(_DRIVE_ID, _ITEM_ID).uri
        assert reread.call_count == 0

    async def test_an_answer_with_no_drive_is_read_again_once_by_the_given_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reread = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_reread_payload())
        )

        summary = await summary_after_write(
            client, _DRIVE_ID, DriveItem(id=_ITEM_ID), item_id=_ITEM_ID, unread=_UNREAD
        )

        assert reread.call_count == 1
        assert summary.uri == DriveFileHandle(_DRIVE_ID, _ITEM_ID).uri
        assert summary.parent_uri is not None

    async def test_a_failed_read_again_raises_the_given_advice_from_the_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reread = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(Advised) as raised:
            _ = await summary_after_write(client, _DRIVE_ID, None, item_id=_ITEM_ID, unread=_UNREAD)

        assert str(raised.value) == _UNREAD
        assert isinstance(raised.value.__cause__, GraphNotFound)
        assert reread.call_count == 1

    async def test_no_answer_and_no_id_raises_the_given_advice_and_reads_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(Advised) as raised:
            _ = await summary_after_write(client, _DRIVE_ID, None, item_id=None, unread=_UNREAD)

        assert str(raised.value) == _UNREAD
        assert len(graph.calls) == 0

    async def test_a_read_again_with_no_drive_raises_the_given_advice(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reread = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_reread_payload(with_drive=False))
        )

        with pytest.raises(Advised) as raised:
            _ = await summary_after_write(
                client, _DRIVE_ID, DriveItem(id=_ITEM_ID), item_id=_ITEM_ID, unread=_UNREAD
            )

        assert str(raised.value) == _UNREAD
        assert reread.call_count == 1


class TestItemAccessRefused:
    def test_it_says_what_did_not_happen_right_after_the_refusal(self) -> None:
        assert item_access_refused("Nothing was moved.").startswith(
            "Microsoft 365 refused this request for the signed-in user. Nothing was moved."
        )

    def test_it_says_that_a_repeat_fails_the_same_way(self) -> None:
        assert "will fail the same way" in item_access_refused("Nothing was moved.")

    def test_it_sends_nobody_to_an_administrator_for_a_grant(self) -> None:
        refusal = item_access_refused("Nothing was moved.")

        assert "administrator" not in refusal
        assert "grant" not in refusal


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

        created = await send_parsed(client, request, DriveItem)

        assert isinstance(created, DriveItem)
        assert created.id == "01SYNTHETICNEW0001"
        assert route.calls.last.request.url.params["@microsoft.graph.conflictBehavior"] == "fail"


def _folder(name: str | None, parent_path: str | None) -> DriveItem:
    return DriveItem(
        id=_FOLDER_ID,
        name=name,
        folder=Folder(child_count=0),
        parent_reference=ItemReference(drive_id=_DRIVE_ID, path=parent_path),
    )


class TestFolderLabel:
    def test_the_root_is_the_top_folder(self) -> None:
        root = DriveItem(id=_FOLDER_ID, name="root", root=Root(), folder=Folder(child_count=2))

        assert folder_label(root) == TOP_FOLDER_LABEL

    @pytest.mark.parametrize("name", [None, ""])
    def test_a_folder_with_no_name_is_unnamed(self, name: str | None) -> None:
        assert folder_label(_folder(name, "/drive/root:/Finance%20Team")) == UNNAMED_FOLDER_LABEL

    def test_the_decoded_parent_path_comes_before_the_name(self) -> None:
        label = folder_label(_folder("Reports", "/drive/root:/Finance%20Team"))

        assert label == "the folder '/Finance Team/Reports'"

    @pytest.mark.parametrize("parent_path", ["/drive/root:", "/drive/root:/"])
    def test_a_folder_under_the_root_starts_with_one_slash(self, parent_path: str) -> None:
        assert folder_label(_folder("Reports", parent_path)) == "the folder '/Reports'"

    @pytest.mark.parametrize("parent_path", [None, "/drives/b%21X/items/01SYNTHETICPARENT0001"])
    def test_a_parent_with_no_breadcrumb_gives_the_name_only(self, parent_path: str | None) -> None:
        assert folder_label(_folder("Reports", parent_path)) == "the folder 'Reports'"

    def test_a_folder_with_no_parent_reference_gives_the_name_only(self) -> None:
        folder = DriveItem(id=_FOLDER_ID, name="Reports", folder=Folder(child_count=0))

        assert folder_label(folder) == "the folder 'Reports'"

    def test_a_long_name_is_cut_for_the_question(self) -> None:
        label = folder_label(_folder("A" * 200, None))

        assert label == f"the folder '{'A' * PREVIEW_CHARACTERS}…'"


class TestItemLabel:
    def test_the_root_is_the_top_folder(self) -> None:
        root = DriveItem(name="root", root=Root(), folder=Folder(child_count=2))

        assert item_label(root) == TOP_FOLDER_LABEL

    @pytest.mark.parametrize("name", [None, ""])
    def test_an_item_with_no_name_is_unnamed(self, name: str | None) -> None:
        assert item_label(DriveItem(name=name)) == UNNAMED_ITEM_LABEL

    def test_a_named_item_is_its_quoted_name(self) -> None:
        assert item_label(DriveItem(name="Budget 2026.xlsx")) == "'Budget 2026.xlsx'"

    def test_a_long_name_is_cut_for_the_question(self) -> None:
        assert item_label(DriveItem(name="A" * 200)) == f"'{'A' * PREVIEW_CHARACTERS}…'"


def _child(parent: ItemReference | None) -> DriveItem:
    return DriveItem(id=_ITEM_ID, name="Budget 2026.xlsx", parent_reference=parent)


class TestParentFolderLabel:
    def test_the_decoded_path_is_the_folder(self) -> None:
        item = _child(ItemReference(drive_id=_DRIVE_ID, path="/drive/root:/Reports/Q1%202026"))

        assert parent_folder_label(item) == "the folder '/Reports/Q1 2026'"

    @pytest.mark.parametrize("path", ["/drive/root:", "/drive/root:/"])
    def test_an_item_at_the_root_is_in_the_top_folder(self, path: str) -> None:
        item = _child(ItemReference(drive_id=_DRIVE_ID, path=path, name="root"))

        assert parent_folder_label(item) == TOP_FOLDER_LABEL

    def test_a_path_with_no_name_gives_the_path(self) -> None:
        item = _child(ItemReference(drive_id=_DRIVE_ID, path="/drive/root:/Reports"))

        assert parent_folder_label(item) == "the folder '/Reports'"

    def test_the_path_wins_over_the_name(self) -> None:
        item = _child(ItemReference(drive_id=_DRIVE_ID, path="/drive/root:/A/Reports", name="X"))

        assert parent_folder_label(item) == "the folder '/A/Reports'"

    @pytest.mark.parametrize("path", [None, "/drives/b%21X/items/01SYNTHETICPARENT0001"])
    def test_a_name_with_no_breadcrumb_gives_the_name(self, path: str | None) -> None:
        item = _child(ItemReference(drive_id=_DRIVE_ID, path=path, name="Reports"))

        assert parent_folder_label(item) == "the folder 'Reports'"

    @pytest.mark.parametrize(
        "parent", [None, ItemReference(drive_id=_DRIVE_ID)], ids=["no-reference", "no-path-no-name"]
    )
    def test_a_parent_with_no_path_and_no_name_is_unnamed(
        self, parent: ItemReference | None
    ) -> None:
        assert parent_folder_label(_child(parent)) == UNNAMED_FOLDER_LABEL

    def test_a_path_by_drive_id_drops_everything_up_to_the_first_colon(self) -> None:
        item = _child(ItemReference(drive_id=_DRIVE_ID, path="/drives/b%21X/root:/A"))

        assert parent_folder_label(item) == "the folder '/A'"


_SENTENCE_END = re.compile(r"(?<=\.)\s+")


class TestHandleSources:
    @pytest.mark.parametrize(
        "sources", [ITEM_HANDLE_SOURCES, FOLDER_HANDLE_SOURCES], ids=["item", "folder"]
    )
    def test_every_sentence_has_20_words_or_fewer(self, sources: str) -> None:
        assert max(len(sentence.split()) for sentence in _SENTENCE_END.split(sources)) <= 20

    def test_the_item_sources_name_the_three_tools_that_give_an_item_handle(self) -> None:
        for tool in (
            "sharepoint_search_files",
            "sharepoint_browse_folder",
            "sharepoint_resolve_url",
        ):
            assert tool in ITEM_HANDLE_SOURCES

    def test_the_folder_sources_name_the_four_tools_and_both_handle_fields(self) -> None:
        for source in (
            "sharepoint_browse_folder",
            "sharepoint_search_files",
            "sharepoint_resolve_url",
            "sharepoint_list_drives",
            "`parent_uri`",
            "`root_uri` of a drive",
        ):
            assert source in FOLDER_HANDLE_SOURCES


def _label_spellings(source: pathlib.Path) -> list[tuple[int, str]]:
    return [
        (node.lineno, node.value)
        for node in ast.walk(ast.parse(source.read_text()))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in _LABELS | _RETIRED_LABELS
    ]


def _tool_id(source: pathlib.Path) -> str:
    return source.stem


class TestOnlyTheOwnerSpellsTheQuestionLabels:
    def test_the_owner_spells_each_label_once(self) -> None:
        assert sorted(value for _line, value in _label_spellings(_OWNER)) == sorted(_LABELS)

    def test_the_scan_finds_the_tools_that_ask_about_a_drive_item(self) -> None:
        assert {source.stem for source in _SHAREPOINT_TOOLS} >= {
            "sharepoint_copy_item",
            "sharepoint_create_folder",
            "sharepoint_create_share_link",
            "sharepoint_create_text_file",
            "sharepoint_delete_item",
            "sharepoint_invite",
            "sharepoint_move_item",
            "sharepoint_rename_item",
        }

    @pytest.mark.parametrize("source", _SHAREPOINT_TOOLS, ids=_tool_id)
    def test_no_sharepoint_tool_spells_a_label(self, source: pathlib.Path) -> None:
        found = _label_spellings(source)
        assert not found, (
            f"{source.name} spells a drive item label: {found}. Import the label from "
            + "shared/files.py."
        )


def _imports_unquote(source: pathlib.Path) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "urllib.parse"
        and any(alias.name == "unquote" for alias in node.names)
        for node in ast.walk(ast.parse(source.read_text()))
    )


class TestOnlyTheOwnerDecodesAGraphPath:
    def test_the_owner_imports_unquote(self) -> None:
        assert _imports_unquote(_OWNER)

    @pytest.mark.parametrize("source", _SHAREPOINT_TOOLS, ids=_tool_id)
    def test_no_sharepoint_tool_imports_unquote(self, source: pathlib.Path) -> None:
        assert not _imports_unquote(source), (
            f"{source.name} decodes a path with unquote. Use folder_label or "
            + "parent_folder_label from shared/files.py."
        )


def _is_a_name(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "name"


def _quoted_names(source: str) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "repr"
            and len(node.args) == 1
            and _is_a_name(node.args[0])
        )
        or (
            isinstance(node, ast.FormattedValue)
            and node.conversion == ord("r")
            and _is_a_name(node.value)
        )
    ]


class TestOnlyTheOwnerQuotesAGraphItemName:
    def test_the_scan_finds_a_repr_call_and_an_f_string_field(self) -> None:
        planted = 'label = repr(item.name)\nquestion = f"Move {found.name!r}?"\n'

        assert _quoted_names(planted) == [1, 2]

    def test_the_scan_passes_a_cut_name_and_a_name_the_call_writes(self) -> None:
        planted = 'label = repr(cut(item.name))\nquestion = f"Rename {cut(old.name)!r} {name!r}?"\n'

        assert _quoted_names(planted) == []

    @pytest.mark.parametrize("source", _SHAREPOINT_TOOLS, ids=_tool_id)
    def test_no_sharepoint_tool_quotes_a_graph_item_name(self, source: pathlib.Path) -> None:
        found = _quoted_names(source.read_text())
        assert not found, (
            f"{source.name} quotes a Graph item name whole on lines {found}. A long name then "
            + "fills the question. Use item_label or folder_label from shared/files.py."
        )
