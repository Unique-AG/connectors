import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import File
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphNotFound
from office_365_mcp.shared.handles import OnenotePageHandle, OnenoteSectionHandle
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
        assert "held in memory" in refusal

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
