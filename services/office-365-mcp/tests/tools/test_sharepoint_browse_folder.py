from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.files import ITEM_FIELDS
from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle
from office_365_mcp.tools import PRESETS, TOOL_NAMES
from office_365_mcp.tools import sharepoint_browse_folder as browser

from .conftest import GRAPH_V1

_MY_DRIVE = "/me/drive"

_DRIVE_ID = "b-SYNTHETIC-drive-0001"
_OTHER_DRIVE_ID = "b-SYNTHETIC-drive-0002"

_REPORTS_ID = "01SYNTHETICREPORTS"
_BUDGET_ID = "01SYNTHETICBUDGET"
_NOTES_ID = "01SYNTHETICNOTES"

_ROOT_CHILDREN = f"/drives/{_DRIVE_ID}/items/root/children"
_REPORTS_CHILDREN = f"/drives/{_DRIVE_ID}/items/{_REPORTS_ID}/children"


def _drive_payload(drive_id: str = _DRIVE_ID) -> httpx.Response:
    return httpx.Response(200, json={"id": drive_id, "driveType": "business"})


def _item_payload(
    item_id: str,
    *,
    name: str | None = "Q4 report.docx",
    is_folder: bool = False,
    drive_id: str | None = _DRIVE_ID,
    size: int | None = 20481,
    child_count: int | None = 3,
    created: str | None = "2026-01-04T08:11:00Z",
    modified: str | None = "2026-02-10T14:00:00Z",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": item_id,
        "name": name,
        "size": size,
        "webUrl": f"https://contoso.sharepoint.invalid/items/{item_id}",
        "createdDateTime": created,
        "lastModifiedDateTime": modified,
        "createdBy": {"user": {"displayName": "Grace Hopper"}},
        "lastModifiedBy": {"user": {"displayName": "Ada Lovelace"}},
        "parentReference": {
            "driveType": "business",
            "path": "/drive/root:/Reports",
            **({} if drive_id is None else {"driveId": drive_id}),
        },
    }
    if is_folder:
        payload["folder"] = {"childCount": child_count}
    else:
        payload["file"] = {"mimeType": "application/pdf"}
    return payload


def _page(*items: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(items)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _numbered_level(count: int) -> httpx.Response:
    return _page(
        *(
            _item_payload(f"01SYNTHETICITEM{number:04d}", name=f"item-{number:04d}")
            for number in range(count)
        )
    )


def _serve_in_two_pages(
    graph: respx.MockRouter, first: list[dict[str, object]], second: list[dict[str, object]]
) -> None:
    graph.get(_ROOT_CHILDREN, params={"$skiptoken": "second"}).mock(return_value=_page(*second))
    graph.get(_ROOT_CHILDREN).mock(
        return_value=_page(*first, next_link=f"{GRAPH_V1}{_ROOT_CHILDREN}?$skiptoken=second")
    )


@pytest.fixture
def my_drive(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_MY_DRIVE).mock(return_value=_drive_payload())


@pytest.fixture
def root_children(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_ROOT_CHILDREN)


@pytest.fixture
def reports_children(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_REPORTS_CHILDREN)


class TestTheLevelItAsksFor:
    async def test_no_folder_reaches_the_top_of_the_users_own_onedrive(
        self,
        client: GraphServiceClient,
        my_drive: respx.Route,
        root_children: respx.Route,
        reports_children: respx.Route,
    ) -> None:
        root_children.mock(return_value=_page(_item_payload(_BUDGET_ID)))

        _ = await browser.browse_folder(client, limit=25)

        assert my_drive.call_count == 1
        assert root_children.call_count == 1
        assert reports_children.call_count == 0

    def test_the_startup_probe_calls_this_tool_with_no_arguments_at_all(self) -> None:
        assert browser.GRAPH_CALL_EXAMPLE == {}

    async def test_a_folder_handle_asks_for_that_folders_children(
        self,
        client: GraphServiceClient,
        my_drive: respx.Route,
        root_children: respx.Route,
        reports_children: respx.Route,
    ) -> None:
        reports_children.mock(return_value=_page(_item_payload(_BUDGET_ID)))

        _ = await browser.browse_folder(
            client, folder=DriveFolderHandle(_DRIVE_ID, _REPORTS_ID).uri, limit=25
        )

        assert reports_children.call_count == 1
        assert root_children.call_count == 0
        assert my_drive.call_count == 0, (
            "a handle already carries the drive, so nothing resolves it"
        )

    async def test_a_handle_from_another_drive_is_read_out_of_that_drive(
        self, client: GraphServiceClient, graph: respx.MockRouter, my_drive: respx.Route
    ) -> None:
        elsewhere = graph.get(f"/drives/{_OTHER_DRIVE_ID}/items/{_REPORTS_ID}/children").mock(
            return_value=_page(_item_payload(_BUDGET_ID, drive_id=_OTHER_DRIVE_ID))
        )

        _ = await browser.browse_folder(
            client, folder=DriveFolderHandle(_OTHER_DRIVE_ID, _REPORTS_ID).uri, limit=25
        )

        assert elsewhere.call_count == 1
        assert my_drive.call_count == 0

    @pytest.mark.usefixtures("my_drive")
    async def test_it_asks_for_every_field_a_row_is_built_from(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(return_value=_page(_item_payload(_BUDGET_ID)))

        _ = await browser.browse_folder(client, limit=25)

        params = root_children.calls.last.request.url.params
        assert params["$select"].split(",") == list(ITEM_FIELDS)

    @pytest.mark.usefixtures("my_drive")
    async def test_it_neither_filters_nor_orders_this_collection(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(return_value=_page(_item_payload(_BUDGET_ID)))

        _ = await browser.browse_folder(client, limit=25)

        params = root_children.calls.last.request.url.params
        assert "$filter" not in params
        assert "$orderby" not in params

    @pytest.mark.usefixtures("my_drive")
    async def test_the_window_is_asked_of_graph_rather_than_only_applied_here(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(return_value=_page(_item_payload(_BUDGET_ID)))

        _ = await browser.browse_folder(client, limit=7)

        assert root_children.calls.last.request.url.params["$top"] == "7"

    @pytest.mark.usefixtures("my_drive")
    async def test_a_limit_of_500_reaches_graph_as_top(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(return_value=_page(_item_payload(_BUDGET_ID)))

        _ = await browser.browse_folder(client, limit=500)

        assert root_children.calls.last.request.url.params["$top"] == "500"

    @pytest.mark.parametrize("limit", [0, -1])
    async def test_a_limit_below_one_is_a_programming_error(
        self, client: GraphServiceClient, limit: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await browser.browse_folder(client, limit=limit)


class TestTheLevelItAnswers:
    @pytest.mark.usefixtures("my_drive")
    async def test_a_file_and_a_folder_are_told_apart_and_handled_apart(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(
            return_value=_page(
                _item_payload(_BUDGET_ID, name="Budget.xlsx"),
                _item_payload(_REPORTS_ID, name="Reports", is_folder=True),
            )
        )

        level = await browser.browse_folder(client, limit=25)

        assert [row.is_folder for row in level.items] == [False, True]
        assert [row.uri for row in level.items] == [
            DriveFileHandle(_DRIVE_ID, _BUDGET_ID).uri,
            DriveFolderHandle(_DRIVE_ID, _REPORTS_ID).uri,
        ]

    @pytest.mark.usefixtures("my_drive")
    async def test_a_row_names_who_created_the_item_apart_from_who_last_changed_it(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(return_value=_page(_item_payload(_BUDGET_ID)))

        row = (await browser.browse_folder(client, limit=25)).items[0]

        assert row.created_by == "Grace Hopper"
        assert row.last_modified_by == "Ada Lovelace"

    @pytest.mark.usefixtures("my_drive")
    async def test_an_item_that_an_application_created_names_no_creator(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(
            return_value=_page(
                {
                    **_item_payload(_BUDGET_ID),
                    "createdBy": {"application": {"displayName": "Contoso Sync"}},
                }
            )
        )

        row = (await browser.browse_folder(client, limit=25)).items[0]

        assert row.created_by is None

    @pytest.mark.usefixtures("my_drive")
    async def test_a_folder_handle_it_minted_browses_that_folder(
        self,
        client: GraphServiceClient,
        root_children: respx.Route,
        reports_children: respx.Route,
    ) -> None:
        root_children.mock(
            return_value=_page(_item_payload(_REPORTS_ID, name="Reports", is_folder=True))
        )
        reports_children.mock(return_value=_page(_item_payload(_BUDGET_ID, name="Budget.xlsx")))

        reports = (await browser.browse_folder(client, limit=25)).items[0]
        below = await browser.browse_folder(client, folder=reports.uri, limit=25)

        assert [row.name for row in below.items] == ["Budget.xlsx"]

    @pytest.mark.usefixtures("my_drive")
    async def test_an_item_microsoft_named_no_drive_for_is_left_out(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(
            return_value=_page(
                _item_payload(_BUDGET_ID, name="Budget.xlsx"),
                _item_payload(_NOTES_ID, name="Notes.txt", drive_id=None),
            )
        )

        level = await browser.browse_folder(client, limit=25)

        assert [row.name for row in level.items] == ["Budget.xlsx"]

    @pytest.mark.usefixtures("my_drive")
    async def test_the_pages_of_one_level_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_ROOT_CHILDREN, params={"$skiptoken": "second"}).mock(
            return_value=_page(_item_payload(_NOTES_ID, name="Notes.txt"))
        )
        graph.get(_ROOT_CHILDREN).mock(
            return_value=_page(
                _item_payload(_BUDGET_ID, name="Budget.xlsx"),
                next_link=f"{GRAPH_V1}{_ROOT_CHILDREN}?$skiptoken=second",
            )
        )

        level = await browser.browse_folder(client, limit=25)

        assert [row.name for row in level.items] == ["Budget.xlsx", "Notes.txt"]
        assert level.capped is False, "the walk reached the end of this level"

    @pytest.mark.usefixtures("my_drive")
    async def test_a_cap_that_left_more_of_the_level_on_offer_says_capped(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(
            return_value=_page(
                _item_payload(_BUDGET_ID, name="Budget.xlsx"),
                _item_payload(_NOTES_ID, name="Notes.txt"),
            )
        )

        level = await browser.browse_folder(client, limit=1)

        assert [row.name for row in level.items] == ["Budget.xlsx"]
        assert level.capped is True

    @pytest.mark.usefixtures("my_drive")
    async def test_a_window_filled_exactly_by_the_end_of_the_level_is_not_capped(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(
            return_value=_page(
                _item_payload(_BUDGET_ID, name="Budget.xlsx"),
                _item_payload(_NOTES_ID, name="Notes.txt"),
            )
        )

        level = await browser.browse_folder(client, limit=2)

        assert len(level.items) == 2
        assert level.capped is False

    async def test_an_empty_folder_answers_an_empty_level(
        self, client: GraphServiceClient, reports_children: respx.Route
    ) -> None:
        reports_children.mock(return_value=_page())

        level = await browser.browse_folder(
            client, folder=DriveFolderHandle(_DRIVE_ID, _REPORTS_ID).uri, limit=25
        )

        assert level.items == []
        assert level.capped is False, "an empty level is the whole of it, not a cap"


class TestTheOrderItGives:
    @pytest.mark.usefixtures("my_drive")
    @pytest.mark.parametrize(
        ("order_by", "expected"),
        [
            ("name", ["apple.txt", "banana.txt", "Cherry.txt"]),
            ("last_modified", ["banana.txt", "apple.txt", "Cherry.txt"]),
            ("created", ["Cherry.txt", "banana.txt", "apple.txt"]),
            ("size", ["Cherry.txt", "apple.txt", "banana.txt"]),
        ],
    )
    async def test_each_key_orders_the_items_of_both_pages_together(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        order_by: browser.OrderBy,
        expected: list[str],
    ) -> None:
        _serve_in_two_pages(
            graph,
            [
                _item_payload(
                    _BUDGET_ID,
                    name="banana.txt",
                    size=10,
                    created="2026-01-02T00:00:00Z",
                    modified="2026-03-01T00:00:00Z",
                ),
                _item_payload(
                    _NOTES_ID,
                    name="Cherry.txt",
                    size=300,
                    created="2026-01-03T00:00:00Z",
                    modified="2026-01-01T00:00:00Z",
                ),
            ],
            [
                _item_payload(
                    _REPORTS_ID,
                    name="apple.txt",
                    size=200,
                    created="2026-01-01T00:00:00Z",
                    modified="2026-02-01T00:00:00Z",
                )
            ],
        )

        level = await browser.browse_folder(client, limit=25, order_by=order_by)

        assert [row.name for row in level.items] == expected

    @pytest.mark.usefixtures("my_drive")
    @pytest.mark.parametrize(
        ("order_by", "wire_key"),
        [
            ("name", "name"),
            ("last_modified", "lastModifiedDateTime"),
            ("created", "createdDateTime"),
            ("size", "size"),
        ],
    )
    async def test_an_item_with_no_value_for_the_key_comes_last(
        self,
        client: GraphServiceClient,
        root_children: respx.Route,
        order_by: browser.OrderBy,
        wire_key: str,
    ) -> None:
        root_children.mock(
            return_value=_page(
                {**_item_payload(_NOTES_ID, name="Notes.txt"), wire_key: None},
                _item_payload(_BUDGET_ID, name="Budget.xlsx"),
                _item_payload(_REPORTS_ID, name="Reports"),
            )
        )

        level = await browser.browse_folder(client, limit=25, order_by=order_by)

        assert level.items[-1].uri == DriveFileHandle(_DRIVE_ID, _NOTES_ID).uri

    @pytest.mark.usefixtures("my_drive")
    async def test_equal_values_fall_back_to_the_name_even_when_the_key_runs_downward(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(
            return_value=_page(
                _item_payload(_NOTES_ID, name="c.txt", size=5),
                _item_payload(_BUDGET_ID, name="A.txt", size=5),
                _item_payload(_REPORTS_ID, name="z.txt", size=9),
                _item_payload("01SYNTHETICOTHER", name="b.txt", size=5),
            )
        )

        level = await browser.browse_folder(client, limit=25, order_by="size")

        assert [row.name for row in level.items] == ["z.txt", "A.txt", "b.txt", "c.txt"]

    @pytest.mark.usefixtures("my_drive")
    async def test_the_cut_to_the_limit_comes_after_the_sort(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(
            return_value=_page(
                _item_payload(_NOTES_ID, name="Small.txt", size=1),
                _item_payload(_BUDGET_ID, name="Big.xlsx", size=900),
            )
        )

        level = await browser.browse_folder(client, limit=1, order_by="size")

        assert [row.name for row in level.items] == ["Big.xlsx"]
        assert level.capped is True, "the cut dropped an item"
        assert level.order_covers_level is True, "the read still reached the end of the level"

    @pytest.mark.usefixtures("my_drive")
    async def test_a_sorted_level_that_fits_the_limit_is_not_capped(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(
            return_value=_page(
                _item_payload(_NOTES_ID, name="Notes.txt"),
                _item_payload(_BUDGET_ID, name="Budget.xlsx"),
            )
        )

        level = await browser.browse_folder(client, limit=2, order_by="name")

        assert [row.name for row in level.items] == ["Budget.xlsx", "Notes.txt"]
        assert level.capped is False
        assert level.order_covers_level is True

    @pytest.mark.usefixtures("my_drive")
    async def test_an_item_left_out_for_want_of_a_drive_does_not_count_as_a_cut(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(
            return_value=_page(
                _item_payload(_BUDGET_ID, name="Budget.xlsx"),
                _item_payload(_NOTES_ID, name="Notes.txt", drive_id=None),
            )
        )

        level = await browser.browse_folder(client, limit=1, order_by="name")

        assert [row.name for row in level.items] == ["Budget.xlsx"]
        assert level.capped is False

    @pytest.mark.usefixtures("my_drive")
    async def test_a_level_of_1000_items_is_read_to_its_end(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(return_value=_numbered_level(1000))

        level = await browser.browse_folder(client, limit=1000, order_by="name")

        assert len(level.items) == 1000
        assert level.order_covers_level is True
        assert level.capped is False

    @pytest.mark.usefixtures("my_drive")
    async def test_a_level_of_1001_items_stops_at_1000_and_says_the_order_is_partial(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(return_value=_numbered_level(1001))

        level = await browser.browse_folder(client, limit=1000, order_by="name")

        assert len(level.items) == 1000
        assert level.items[-1].name == "item-0999"
        assert level.order_covers_level is False
        assert level.capped is True, "the read stopped with more of the level on offer"

    @pytest.mark.usefixtures("my_drive")
    async def test_without_order_by_the_order_says_nothing_about_the_level(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(return_value=_page(_item_payload(_BUDGET_ID)))

        level = await browser.browse_folder(client, limit=25)

        assert level.order_covers_level is None

    @pytest.mark.usefixtures("my_drive")
    async def test_with_order_by_graph_gets_neither_a_top_nor_an_orderby(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(return_value=_page(_item_payload(_BUDGET_ID)))

        _ = await browser.browse_folder(client, limit=7, order_by="size")

        params = root_children.calls.last.request.url.params
        assert "$top" not in params
        assert "$orderby" not in params
        assert params["$select"].split(",") == list(ITEM_FIELDS)


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "folder",
        [
            "Reports",
            "/Reports/2026",
            _REPORTS_ID,
            "https://contoso.sharepoint.invalid/items/01SYNTHETICREPORTS",
            "sharepoint:///folders/",
            DriveFileHandle(_DRIVE_ID, _BUDGET_ID).uri,
        ],
    )
    async def test_a_folder_that_is_not_a_folder_handle_never_reaches_graph(
        self,
        client: GraphServiceClient,
        my_drive: respx.Route,
        root_children: respx.Route,
        folder: str,
    ) -> None:
        with pytest.raises(ToolError, match="folder handle"):
            _ = await browser.browse_folder(client, folder=folder, limit=25)

        assert my_drive.call_count == 0
        assert root_children.call_count == 0

    async def test_the_refusal_says_how_to_reach_the_users_own_onedrive(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="Omit `folder`"):
            _ = await browser.browse_folder(client, folder="Reports", limit=25)

    async def test_the_refusal_shows_the_same_handle_shape_as_the_argument(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as raised:
            _ = await browser.browse_folder(client, folder="Reports", limit=25)

        assert "sharepoint:///folders/{drive_id}/{item_id}" in str(raised.value)


class TestGraphFailures:
    @pytest.mark.usefixtures("my_drive")
    async def test_a_refusal_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, root_children: respx.Route
    ) -> None:
        root_children.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await browser.browse_folder(client, limit=25)

    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        assert browser.GRAPH_PERMISSIONS == ("Files.Read.All",)

    def test_a_stale_folder_handle_is_answered_with_the_recovery_that_works(self) -> None:
        assert "deleted" in browser.GRAPH_NOT_FOUND
        assert "fails in the same way" in browser.GRAPH_NOT_FOUND


async def _folder_description(transport: httpx.AsyncClient) -> str:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    browser.register(mcp, transport)
    tool = await mcp.get_tool(browser.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
    return str(properties["folder"].get("description", ""))


class TestTheSchemaItPublishes:
    async def test_the_folder_argument_names_where_each_kind_of_folder_handle_comes_from(
        self, transport: httpx.AsyncClient
    ) -> None:
        description = await _folder_description(transport)

        assert "sharepoint_list_drives" in description
        assert "`root_uri` of a drive" in description
        assert "`parent_uri`" in description

    async def test_the_folder_argument_names_no_tool_that_a_preset_with_this_tool_lacks(
        self, transport: httpx.AsyncClient
    ) -> None:
        description = await _folder_description(transport)
        named = {name for name in TOOL_NAMES if name in description}
        serving = {
            preset: set(tools) for preset, tools in PRESETS.items() if browser.TOOL_NAME in tools
        }

        assert "sharepoint_resolve_url" not in description
        assert "sharepoint-search" in serving
        lacking = {
            preset: sorted(named - tools) for preset, tools in serving.items() if named - tools
        }
        assert not lacking, f"the folder argument names tools these presets do not serve: {lacking}"

    async def test_the_folder_argument_shows_the_shape_of_a_folder_handle(
        self, transport: httpx.AsyncClient
    ) -> None:
        description = await _folder_description(transport)

        assert "sharepoint:///folders/{drive_id}/{item_id}" in description

    async def test_the_folder_argument_is_described_in_15_to_60_words(
        self, transport: httpx.AsyncClient
    ) -> None:
        description = await _folder_description(transport)

        assert 15 <= len(description.split()) <= 60
