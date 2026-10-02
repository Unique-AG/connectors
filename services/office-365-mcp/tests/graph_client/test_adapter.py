import ast
import json
import pathlib

import httpx
import pytest
import respx
from kiota_abstractions.method import Method
from kiota_abstractions.request_information import RequestInformation
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.folder import Folder
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import (
    GraphForbidden,
    GraphNotFound,
    GraphUnavailable,
    graph_errors,
    no_retry,
    request_with_json_body,
    request_with_query,
    send_no_response_content,
    send_parsed,
)

_SRC = pathlib.Path(__file__).parent.parent.parent / "src" / "office_365_mcp"
_OWNER = _SRC / "graph_client" / "adapter.py"
_SHAREPOINT_TOOLS = sorted((_SRC / "tools").glob("sharepoint_*.py"))

_DRIVE_ID = "b!SYNTHETICDRIVE0000"
_FOLDER_ID = "01SYNTHETICFOLDER0000"
_CHILDREN = f"/drives/{_DRIVE_ID}/items/{_FOLDER_ID}/children"
_COPY = f"/drives/{_DRIVE_ID}/items/{_FOLDER_ID}/copy"
_CONFLICT = "@microsoft.graph.conflictBehavior"


def _create_folder(client: GraphServiceClient) -> RequestInformation:
    children = client.drives.by_drive_id(_DRIVE_ID).items.by_drive_item_id(_FOLDER_ID).children
    return request_with_json_body(
        client,
        Method.POST,
        children.url_template,
        children.path_parameters,
        query={_CONFLICT: "fail"},
        body=DriveItem(name="Q3", folder=Folder()),
    )


def _copy(client: GraphServiceClient) -> RequestInformation:
    copy = client.drives.by_drive_id(_DRIVE_ID).items.by_drive_item_id(_FOLDER_ID).copy
    return request_with_query(Method.POST, copy.url_template, copy.path_parameters, query={})


def _reads_the_adapter(source: pathlib.Path) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(ast.parse(source.read_text()))
        if isinstance(node, ast.Attribute) and node.attr == "request_adapter"
    ]


def _tool_id(source: pathlib.Path) -> str:
    return source.stem


class TestRequestWithJsonBody:
    async def test_the_body_reaches_the_wire_as_json(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_CHILDREN).mock(return_value=httpx.Response(201, json={"id": "new"}))

        _ = await send_parsed(client, _create_folder(client), DriveItem)

        sent = route.calls.last.request
        assert sent.headers["content-type"] == "application/json"
        assert json.loads(sent.content) == {
            "@odata.type": "#microsoft.graph.driveItem",
            "name": "Q3",
            "folder": {},
        }

    async def test_the_query_reaches_the_url(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_CHILDREN).mock(return_value=httpx.Response(201, json={"id": "new"}))

        _ = await send_parsed(client, _create_folder(client), DriveItem)

        assert route.calls.last.request.url.params[_CONFLICT] == "fail"


class TestSendParsed:
    async def test_it_answers_the_model_that_the_factory_makes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post(_CHILDREN).mock(
            return_value=httpx.Response(201, json={"id": "01SYNTHETICNEW0001", "name": "Q3"})
        )

        created = await send_parsed(client, _create_folder(client), DriveItem)

        assert isinstance(created, DriveItem)
        assert created.id == "01SYNTHETICNEW0001"

    async def test_a_404_is_an_error_this_package_can_classify(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post(_CHILDREN).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "not found"}}
            )
        )

        with pytest.raises(GraphNotFound), graph_errors("test_send_parsed"):
            await send_parsed(client, _create_folder(client), DriveItem)

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_the_request_options_of_the_caller_still_apply(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_CHILDREN).mock(return_value=httpx.Response(503))
        request = _create_folder(client)
        request.add_request_options(no_retry())

        with pytest.raises(GraphUnavailable), graph_errors("test_send_parsed"):
            await send_parsed(client, request, DriveItem)

        assert route.call_count == 1


class TestSendNoResponseContent:
    async def test_an_accepted_request_answers_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_COPY).mock(return_value=httpx.Response(202))

        assert await send_no_response_content(client, _copy(client)) is None
        assert route.call_count == 1

    async def test_a_403_is_an_error_this_package_can_classify(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post(_COPY).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden), graph_errors("test_send_no_response_content"):
            await send_no_response_content(client, _copy(client))


class TestOnlyTheOwnerReadsTheAdapter:
    def test_the_owner_reads_it(self) -> None:
        assert _reads_the_adapter(_OWNER)

    def test_the_scan_finds_the_tools_that_send_a_request_of_their_own(self) -> None:
        assert {source.stem for source in _SHAREPOINT_TOOLS} >= {
            "sharepoint_copy_item",
            "sharepoint_create_folder",
            "sharepoint_create_text_file",
            "sharepoint_search_sites",
        }

    @pytest.mark.parametrize("source", _SHAREPOINT_TOOLS, ids=_tool_id)
    def test_no_sharepoint_tool_reads_it(self, source: pathlib.Path) -> None:
        found = _reads_the_adapter(source)
        assert not found, (
            f"{source.name} reads client.request_adapter on lines {found}. Use send_parsed, "
            + "send_no_response_content or request_with_json_body from graph_client."
        )
