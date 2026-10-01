import httpx
import pytest
import respx
from fastmcp import FastMCP
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.handles import DriveFolderHandle, drive_folder_handle
from office_365_mcp.shared.seam import READ_ONLY
from office_365_mcp.tools import sharepoint_browse_folder as browser
from office_365_mcp.tools import sharepoint_list_drives as lister

from .conftest import GRAPH_V1

_MY_DRIVES = "/me/drives"

_DRIVE_ID = "b-SYNTHETIC-drive-0001"
_LIBRARY_ID = "b-SYNTHETIC-drive-0002"


def _drive_payload(
    drive_id: str | None = _DRIVE_ID,
    *,
    name: str | None = "OneDrive",
    drive_type: str | None = "business",
    owner: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": drive_id,
        "name": name,
        "driveType": drive_type,
        "webUrl": "https://contoso-my.sharepoint.invalid/personal/ada/Documents",
        "description": "",
        "owner": {"user": {"displayName": "Ada Lovelace"}} if owner is None else owner,
    }


def _page(*drives: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(drives)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


@pytest.fixture
def my_drives(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_MY_DRIVES)


class TestTheQueryItComposes:
    async def test_it_asks_for_exactly_the_fields_a_row_is_built_from(
        self, client: GraphServiceClient, my_drives: respx.Route
    ) -> None:
        my_drives.mock(return_value=_page(_drive_payload()))

        _ = await lister.list_drives(client)

        assert my_drives.call_count == 1
        assert my_drives.calls.last.request.url.params["$select"].split(",") == [
            "id",
            "name",
            "driveType",
            "webUrl",
            "description",
            "owner",
        ]

    async def test_it_leaves_the_system_drives_hidden(
        self, client: GraphServiceClient, my_drives: respx.Route
    ) -> None:
        my_drives.mock(return_value=_page(_drive_payload()))

        _ = await lister.list_drives(client)

        params = my_drives.calls.last.request.url.params
        assert "system" not in params["$select"].split(",")
        assert "$filter" not in params
        assert "$orderby" not in params
        assert "$expand" not in params


class TestWhatItAnswers:
    async def test_a_drive_carries_what_graph_reported_and_a_handle_for_its_top_folder(
        self, client: GraphServiceClient, my_drives: respx.Route
    ) -> None:
        my_drives.mock(return_value=_page(_drive_payload()))

        drive = (await lister.list_drives(client)).drives[0]

        assert drive.root_uri == DriveFolderHandle(_DRIVE_ID, "root").uri
        assert drive.name == "OneDrive"
        assert drive.drive_type == "business"
        assert drive.web_url == "https://contoso-my.sharepoint.invalid/personal/ada/Documents"
        assert drive.owner_name == "Ada Lovelace"
        assert drive.description == ""

    async def test_an_owner_that_is_not_a_user_answers_no_owner_name(
        self, client: GraphServiceClient, my_drives: respx.Route
    ) -> None:
        my_drives.mock(
            return_value=_page(_drive_payload(owner={"group": {"displayName": "Finance"}}))
        )

        drive = (await lister.list_drives(client)).drives[0]

        assert drive.owner_name is None

    async def test_a_drive_graph_named_nothing_for_answers_nulls_and_not_empty_text(
        self, client: GraphServiceClient, my_drives: respx.Route
    ) -> None:
        my_drives.mock(return_value=httpx.Response(200, json={"value": [{"id": _DRIVE_ID}]}))

        drive = (await lister.list_drives(client)).drives[0]

        assert drive.name is None
        assert drive.drive_type is None
        assert drive.web_url is None
        assert drive.owner_name is None
        assert drive.description is None

    async def test_a_drive_with_no_id_is_left_out(
        self, client: GraphServiceClient, my_drives: respx.Route
    ) -> None:
        my_drives.mock(
            return_value=_page(
                _drive_payload(None, name="Nameless"),
                _drive_payload(_DRIVE_ID, name="OneDrive"),
            )
        )

        listed = await lister.list_drives(client)

        assert [drive.name for drive in listed.drives] == ["OneDrive"]

    async def test_the_pages_of_the_listing_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_MY_DRIVES, params={"$skiptoken": "second"}).mock(
            return_value=_page(_drive_payload(_LIBRARY_ID, name="Archive"))
        )
        graph.get(_MY_DRIVES).mock(
            return_value=_page(
                _drive_payload(_DRIVE_ID, name="OneDrive"),
                next_link=f"{GRAPH_V1}{_MY_DRIVES}?$skiptoken=second",
            )
        )

        listed = await lister.list_drives(client)

        assert [drive.name for drive in listed.drives] == ["OneDrive", "Archive"]
        assert listed.capped is False, "the walk reached the end of the listing"

    async def test_a_scan_limit_that_left_more_drives_on_offer_says_capped(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(lister, "MAX_SCANNED_ITEMS", 1)
        graph.get(_MY_DRIVES, params={"$skiptoken": "second"}).mock(
            return_value=_page(_drive_payload(_LIBRARY_ID, name="Archive"))
        )
        graph.get(_MY_DRIVES).mock(
            return_value=_page(
                _drive_payload(_DRIVE_ID, name="OneDrive"),
                next_link=f"{GRAPH_V1}{_MY_DRIVES}?$skiptoken=second",
            )
        )

        listed = await lister.list_drives(client)

        assert [drive.name for drive in listed.drives] == ["OneDrive"]
        assert listed.capped is True

    async def test_a_user_with_no_drive_answers_an_empty_listing(
        self, client: GraphServiceClient, my_drives: respx.Route
    ) -> None:
        my_drives.mock(return_value=_page())

        listed = await lister.list_drives(client)

        assert listed.drives == []
        assert listed.capped is False, "an empty listing is the whole of it, not a cap"


class TestTheHandleItMints:
    async def test_the_root_uri_parses_as_a_folder_handle(
        self, client: GraphServiceClient, my_drives: respx.Route
    ) -> None:
        my_drives.mock(return_value=_page(_drive_payload()))

        drive = (await lister.list_drives(client)).drives[0]

        assert drive_folder_handle(drive.root_uri) == DriveFolderHandle(_DRIVE_ID, "root")

    async def test_sharepoint_browse_folder_reads_the_top_folder_it_names(
        self, client: GraphServiceClient, graph: respx.MockRouter, my_drives: respx.Route
    ) -> None:
        my_drives.mock(return_value=_page(_drive_payload(_LIBRARY_ID)))
        children = graph.get(f"/drives/{_LIBRARY_ID}/items/root/children").mock(
            return_value=_page()
        )

        drive = (await lister.list_drives(client)).drives[0]
        level = await browser.browse_folder(client, folder=drive.root_uri, limit=25)

        assert children.call_count == 1
        assert level.items == []


class TestTheSchemaItPublishes:
    async def test_it_publishes_no_arguments_at_all(self, transport: httpx.AsyncClient) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters.get("properties", {}) == {}
        assert tool.parameters.get("required", []) == []

    async def test_it_announces_itself_as_read_only(self, transport: httpx.AsyncClient) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.annotations is not None, "a tool with no annotations joins the write surface"
        assert tool.annotations.read_only_hint is READ_ONLY["readOnlyHint"]

    async def test_the_description_sends_a_model_on_to_the_browser_and_away_from_site_libraries(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        description = tool.description or ""
        assert "Pass `root_uri` as `folder` to sharepoint_browse_folder" in description
        assert "does not list the document libraries of SharePoint sites" in description
        assert "use sharepoint_search_files and its `sites` answer" in description

    def test_the_call_that_proves_the_permissions_takes_no_arguments(self) -> None:
        assert lister.GRAPH_CALL_EXAMPLE == {}


class TestGraphFailures:
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, my_drives: respx.Route
    ) -> None:
        my_drives.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await lister.list_drives(client)

    def test_the_permission_is_one_the_sibling_file_tools_already_ask_for(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Files.Read.All",)
        assert lister.GRAPH_PERMISSIONS == browser.GRAPH_PERMISSIONS
