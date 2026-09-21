from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from fastmcp.utilities.types import File
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphNotFound
from office_365_mcp.shared.handles import OnenotePageHandle, OnenoteSectionHandle
from office_365_mcp.shared.notes import resource_id_in
from office_365_mcp.shared.seam import READ_ONLY
from office_365_mcp.tools import onenote_read_resource as reader

RESOURCE_ID = "1-SYNTHETICRESOURCE0000"

_CONTENT_PATH = f"/me/onenote/resources/{RESOURCE_ID}/content"

_VALUE_ADDRESS = (
    f"https://graph.microsoft.com/v1.0/users('synthetic')/onenote/resources/{RESOURCE_ID}/$value"
)
_CONTENT_ADDRESS = f"https://graph.microsoft.com/v1.0/me/onenote/resources/{RESOURCE_ID}/content"

_BYTES = b"\x89PNG\r\nsynthetic-image-bytes"


@pytest.fixture
def content(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_CONTENT_PATH).mock(
        return_value=httpx.Response(200, content=_BYTES, headers={"Content-Type": "image/png"})
    )


async def _read(client: GraphServiceClient, *, resource: str = _VALUE_ADDRESS) -> File:
    return await reader.read_resource(client, resource=resource)


class TestWhatItAsks:
    async def test_it_fetches_the_content_of_the_id_parsed_from_the_address(
        self, client: GraphServiceClient, content: respx.Route
    ) -> None:
        _ = await _read(client)

        assert content.call_count == 1
        assert content.calls.last.request.url.path == f"/v1.0{_CONTENT_PATH}"

    async def test_it_asks_for_octet_stream_or_json(
        self, client: GraphServiceClient, content: respx.Route
    ) -> None:
        _ = await _read(client)

        assert content.calls.last.request.headers["accept"] == (
            "application/octet-stream, application/json"
        )

    async def test_it_carries_no_query_parameters(
        self, client: GraphServiceClient, content: respx.Route
    ) -> None:
        _ = await _read(client)

        assert content.calls.last.request.url.params == httpx.QueryParams()

    async def test_a_content_suffixed_address_resolves_the_same_id(
        self, client: GraphServiceClient, content: respx.Route
    ) -> None:
        _ = await _read(client, resource=_CONTENT_ADDRESS)

        assert content.call_count == 1


class TestWhatComesBack:
    async def test_the_bytes_and_media_type_are_returned_unconverted(
        self, client: GraphServiceClient, content: respx.Route
    ) -> None:
        answer = await _read(client)

        assert isinstance(answer, File)
        assert answer.data == _BYTES
        assert answer.to_resource_content().resource.mime_type == "image/png"
        assert (content.call_count,) == (1,)

    @pytest.mark.usefixtures("content")
    async def test_the_file_is_named_after_the_resource_id(
        self, client: GraphServiceClient
    ) -> None:
        answer = await _read(client)

        assert answer.to_resource_content().resource.uri == f"file:///{RESOURCE_ID}.png"

    async def test_a_missing_content_type_falls_back_to_octet_stream(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=_BYTES))

        answer = await _read(client)

        assert answer.to_resource_content().resource.mime_type == "application/octet-stream"


class TestTheSizeCap:
    async def test_content_exactly_at_the_cap_is_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        body = b"a" * reader.MAX_BYTES
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=body))

        answer = await _read(client)

        assert answer.data == body

    async def test_content_over_the_cap_is_refused_with_the_exact_byte_count(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        body = b"x" * (reader.MAX_BYTES + 1)
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=body))

        with pytest.raises(ToolError) as refused:
            _ = await _read(client)

        refusal = str(refused.value)
        assert f"{len(body):,} bytes" in refusal
        assert f"{reader.MAX_BYTES:,} bytes" in refusal
        assert "arrive in one message" in refusal

    async def test_empty_content_is_refused_rather_than_returned_as_an_empty_file(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=b""))

        with pytest.raises(ToolError, match="sent no content"):
            _ = await _read(client)


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            OnenotePageHandle("0-SYNTHETICPAGE0000!0001").uri,
            OnenoteSectionHandle("0-SYNTHETICSECTION00!0001").uri,
            "https://onenote.example.invalid/pages/sprint-notes",
            "not a graph address at all",
            "",
        ],
    )
    async def test_a_value_that_is_not_a_resource_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="onenote_read_page"):
            _ = await _read(client, resource=value)

        assert graph.calls.call_count == 0


class TestGraphFailures:
    async def test_a_404_on_the_content_is_a_graph_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CONTENT_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _read(client)

    def test_the_not_found_advice_names_onenote_read_page_and_a_fresh_address(self) -> None:
        assert "onenote_read_page" in reader.GRAPH_NOT_FOUND
        assert "fails again" in reader.GRAPH_NOT_FOUND


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    reader.register(mcp, transport)
    tool = await mcp.get_tool(reader.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestHowItDeclaresItself:
    def test_the_permission_is_notes_read(self) -> None:
        assert reader.GRAPH_PERMISSIONS == ("Notes.Read",)

    def test_the_call_example_is_a_resource_address(self) -> None:
        assert set(reader.GRAPH_CALL_EXAMPLE) == {"resource"}

    def test_the_call_example_parses_as_a_resource_id(self) -> None:
        example = cast("Mapping[str, str]", reader.GRAPH_CALL_EXAMPLE)
        assert resource_id_in(example["resource"]) is not None

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(reader.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_one_argument_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"resource"}

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_read_only(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, "a tool with no annotations joins the write surface"
        assert annotations.read_only_hint is READ_ONLY["readOnlyHint"]
