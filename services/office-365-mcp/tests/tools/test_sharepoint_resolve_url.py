import base64
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.files import ITEM_FIELDS, DriveItemSummary
from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle
from office_365_mcp.shared.seam import READ_ONLY
from office_365_mcp.tools import sharepoint_resolve_url as resolver

DRIVE_ID = "b!SYNTHETICDRIVE0000"
ITEM_ID = "01SYNTHETICITEM0000"
PARENT_ID = "01SYNTHETICPARENT00"

_LINK = "https://contoso.sharepoint.invalid/:w:/s/Finance/SYNTHETICLINK0000"

_DOCUMENTED_EXAMPLE = (
    "https://onedrive.live.com/redir?resid=1231244193912!12&authKey=1201919!12921!1"
)
_GIVES_PLUS_AND_SLASH = "https://contoso.sharepoint.invalid/:w:/s/Finance/E~aa?e=1"
_GIVES_ONE_PAD = "https://contoso.sharepoint.invalid/:w:/s/Finance/Eaa?e=1"
_GIVES_PLUS_AND_TWO_PADS = "https://contoso.sharepoint.invalid/:w:/s/Finance/E~?e=1"
_GIVES_SLASH_AND_TWO_PADS = "https://contoso.sharepoint.invalid/:w:/s/Finance/E??e=1"

_ENCODED_LINKS = (
    _DOCUMENTED_EXAMPLE,
    _GIVES_PLUS_AND_SLASH,
    _GIVES_ONE_PAD,
    _GIVES_PLUS_AND_TWO_PADS,
    _GIVES_SLASH_AND_TWO_PADS,
)


def _documented_token(url: str) -> str:
    encoded = base64.b64encode(url.encode("utf-8")).decode("ascii")
    return "u!" + encoded.rstrip("=").replace("/", "_").replace("+", "-")


def _item_payload(*, is_folder: bool = False, drive_id: str | None = DRIVE_ID) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": ITEM_ID,
        "name": "Reports" if is_folder else "Quarterly.pdf",
        "size": 20481,
        "webUrl": "https://contoso.sharepoint.invalid/sites/Finance/Quarterly.pdf",
        "createdDateTime": "2026-01-04T08:11:00Z",
        "lastModifiedDateTime": "2026-02-10T14:00:00Z",
        "lastModifiedBy": {"user": {"displayName": "Ada Lovelace"}},
        "parentReference": {
            "id": PARENT_ID,
            "driveType": "documentLibrary",
            "path": "/drive/root:/Reports",
            **({} if drive_id is None else {"driveId": drive_id}),
        },
    }
    if is_folder:
        payload["folder"] = {"childCount": 3}
    else:
        payload["file"] = {"mimeType": "application/pdf"}
    return payload


@pytest.fixture
def shared(graph: respx.MockRouter) -> respx.Route:
    return graph.route().mock(return_value=httpx.Response(200, json=_item_payload()))


async def _resolve(client: GraphServiceClient, *, url: str = _LINK) -> DriveItemSummary:
    return await resolver.resolve_url(client, url=url)


class TestWhatItAsks:
    def test_the_links_under_test_reach_every_character_the_encoding_replaces(self) -> None:
        standard = [base64.b64encode(url.encode()).decode("ascii") for url in _ENCODED_LINKS]

        assert [encoded for encoded in standard if "+" in encoded]
        assert [encoded for encoded in standard if "/" in encoded]
        assert [encoded for encoded in standard if encoded.endswith("=") and encoded[-2] != "="]
        assert [encoded for encoded in standard if encoded.endswith("==")]

    @pytest.mark.parametrize("url", _ENCODED_LINKS)
    async def test_the_link_reaches_graph_encoded_as_microsoft_documents(
        self, client: GraphServiceClient, shared: respx.Route, url: str
    ) -> None:
        _ = await _resolve(client, url=url)

        assert shared.call_count == 1
        assert shared.calls.last.request.url.path == (
            f"/v1.0/shares/{_documented_token(url)}/driveItem"
        )

    async def test_whitespace_around_the_link_stays_out_of_the_token(
        self, client: GraphServiceClient, shared: respx.Route
    ) -> None:
        _ = await _resolve(client, url=f"  {_LINK}\n")

        assert shared.calls.last.request.url.path == (
            f"/v1.0/shares/{_documented_token(_LINK)}/driveItem"
        )

    async def test_it_asks_for_the_fields_every_drive_tool_agrees_on(
        self, client: GraphServiceClient, shared: respx.Route
    ) -> None:
        _ = await _resolve(client)

        selected = shared.calls.last.request.url.params["$select"]
        assert selected.split(",") == list(ITEM_FIELDS)

    async def test_it_sends_no_prefer_header(
        self, client: GraphServiceClient, shared: respx.Route
    ) -> None:
        _ = await _resolve(client)

        assert "Prefer" not in shared.calls.last.request.headers, (
            "redeemSharingLink grants the caller lasting access to the item, and "
            + "redeemSharingLinkIfNecessary grants access for the length of one request"
        )


class TestWhatItAnswers:
    @pytest.mark.usefixtures("shared")
    async def test_a_file_link_answers_a_file_handle(self, client: GraphServiceClient) -> None:
        answer = await _resolve(client)

        assert answer.uri == DriveFileHandle(DRIVE_ID, ITEM_ID).uri
        assert answer.is_folder is False
        assert answer.name == "Quarterly.pdf"
        assert answer.parent_uri == DriveFolderHandle(DRIVE_ID, PARENT_ID).uri

    async def test_a_folder_link_answers_a_folder_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route().mock(return_value=httpx.Response(200, json=_item_payload(is_folder=True)))

        answer = await _resolve(client)

        assert answer.uri == DriveFolderHandle(DRIVE_ID, ITEM_ID).uri
        assert answer.is_folder is True
        assert answer.child_count == 3

    async def test_an_item_with_no_drive_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route().mock(return_value=httpx.Response(200, json=_item_payload(drive_id=None)))

        with pytest.raises(ToolError, match="did not report the drive") as refused:
            _ = await _resolve(client)

        assert "open the link in a browser" in str(refused.value)


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "url",
        [
            "",
            "   ",
            "Quarterly.docx",
            "/sites/Finance/Shared Documents/Quarterly.docx",
            ITEM_ID,
            "contoso.sharepoint.invalid/:w:/s/Finance/SYNTHETICLINK0000",
            "http://contoso.sharepoint.invalid/:w:/s/Finance/SYNTHETICLINK0000",
            "ftp://contoso.sharepoint.invalid/Quarterly.docx",
            "https://",
            "https:///sites/Finance/Quarterly.docx",
            "https://[contoso.sharepoint.invalid/Quarterly.docx",
            DriveFileHandle(DRIVE_ID, ITEM_ID).uri,
            DriveFolderHandle(DRIVE_ID, ITEM_ID).uri,
        ],
    )
    async def test_a_value_that_is_not_a_web_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, url: str
    ) -> None:
        with pytest.raises(ToolError, match="did not get a web address"):
            _ = await _resolve(client, url=url)

        assert len(graph.calls) == 0

    async def test_the_refusal_sends_a_handle_to_the_tools_that_take_it(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _resolve(client, url=DriveFileHandle(DRIVE_ID, ITEM_ID).uri)

        assert "already a handle" in str(refused.value)
        assert "sharepoint_read_file" in str(refused.value)
        assert "sharepoint_browse_folder" in str(refused.value)


class TestGraphFailures:
    async def test_a_404_is_a_graph_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route().mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _resolve(client)

    async def test_a_403_is_a_graph_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route().mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "Forbidden"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _resolve(client)


async def _registered(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    resolver.register(mcp, transport)
    tool = await mcp.get_tool(resolver.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool


class TestHowItDeclaresItself:
    def test_the_permission_is_one_that_microsoft_lists_for_this_call(self) -> None:
        assert resolver.GRAPH_PERMISSIONS == ("Files.ReadWrite.All",), (
            "Microsoft lists Files.ReadWrite, Files.ReadWrite.All and Sites.ReadWrite.All for "
            + "GET /shares and lists no read-only file permission"
        )

    def test_the_graph_call_has_a_step_of_its_own(self) -> None:
        assert resolver.STEP == "shared_item"

    async def test_the_call_example_reaches_graph(
        self, client: GraphServiceClient, shared: respx.Route
    ) -> None:
        assert set(resolver.GRAPH_CALL_EXAMPLE) == {"url"}

        _ = await _resolve(client, url=cast("str", resolver.GRAPH_CALL_EXAMPLE["url"]))

        assert shared.call_count == 1

    async def test_it_takes_one_argument_and_it_is_the_link(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert set(properties) == {"url"}
        assert tool.parameters["required"] == ["url"]
        url = cast("Mapping[str, object]", properties["url"])
        assert url["minLength"] == 1

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_read_only(self, transport: httpx.AsyncClient) -> None:
        tool = await _registered(transport)

        assert tool.annotations is not None, "a tool with no annotations joins the write surface"
        assert tool.annotations.read_only_hint is READ_ONLY["readOnlyHint"]
        assert tool.title == "Resolve a File Link"

    async def test_the_answer_is_one_item_with_its_handle(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert tool.output_schema is not None
        assert tool.output_schema["type"] == "object"
        properties = cast("Mapping[str, object]", tool.output_schema["properties"])
        assert {"uri", "is_folder", "parent_uri"} <= set(properties)

    async def test_the_description_sends_each_handle_to_the_tool_that_takes_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        described = (await _registered(transport)).description or ""

        assert "Pass a file handle to sharepoint_read_file" in described
        assert "a folder handle to sharepoint_browse_folder" in described
        assert "use sharepoint_search_files instead" in described

    async def test_the_description_says_the_link_gives_no_new_access(
        self, transport: httpx.AsyncClient
    ) -> None:
        described = (await _registered(transport)).description or ""

        assert "does not accept the sharing invitation that a link carries" in described
        assert "the signed-in user gets no new access to the item" in described
        assert "Microsoft documents this lookup for sharing links" in described
        assert "Another form of web address can fail" in described

    def test_a_404_names_the_causes_and_the_recovery(self) -> None:
        assert "expired or removed" in resolver.GRAPH_NOT_FOUND
        assert "does not open for the signed-in user" in resolver.GRAPH_NOT_FOUND
        assert "sharepoint_search_files" in resolver.GRAPH_NOT_FOUND
        assert "open the link in a browser" in resolver.GRAPH_NOT_FOUND
        assert "the call will fail the same way" in resolver.GRAPH_NOT_FOUND
