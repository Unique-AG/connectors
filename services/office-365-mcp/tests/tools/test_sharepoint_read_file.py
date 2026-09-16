import base64
from collections.abc import Iterator, Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.utilities.types import File
from mcp.types import BlobResourceContents, TextResourceContents
from msgraph.graph_service_client import GraphServiceClient
from prometheus_client import generate_latest
from unique_toolkit.monitoring import REGISTRY

from office_365_mcp.config import AppConfig
from office_365_mcp.graph_client import GRAPH_STEPS_TOTAL, GraphNotFound
from office_365_mcp.metrics import configure_metrics
from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle, drive_file_handle
from office_365_mcp.tools import sharepoint_read_file as reader

DRIVE_ID = "b!SYNTHETICDRIVE0000"
ITEM_ID = "01SYNTHETICFILE0000"

_ITEM_PATH = "/drives/b%21SYNTHETICDRIVE0000/items/01SYNTHETICFILE0000"
_CONTENT_PATH = f"{_ITEM_PATH}/content"

_FILE = DriveFileHandle(DRIVE_ID, ITEM_ID).uri
_FOLDER = DriveFolderHandle(DRIVE_ID, ITEM_ID).uri

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_NAME = "Quarterly-report.docx"
_WEB_URL = "https://contoso.sharepoint.invalid/sites/finance/Shared-Documents/Quarterly.docx"

_BYTES = b"PK\x03\x04\x14\x00\x06\x00synthetic"
_SIZE = len(_BYTES)


def _payload(
    *,
    name: str | None = _NAME,
    size: int | None = _SIZE,
    mime_type: str | None = _DOCX,
    web_url: str | None = _WEB_URL,
    a_folder: bool = False,
) -> dict[str, object]:
    facet: dict[str, object] = (
        {"folder": {"childCount": 4}} if a_folder else {"file": {"mimeType": mime_type}}
    )
    return {
        "id": ITEM_ID,
        "name": name,
        "size": size,
        "webUrl": web_url,
        "lastModifiedDateTime": "2026-03-04T09:15:00Z",
        "parentReference": {"driveId": DRIVE_ID, "path": "/drive/root:/Reports"},
        **facet,
    }


@pytest.fixture
def item(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=_payload()))


@pytest.fixture
def content(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=_BYTES))


async def _read(client: GraphServiceClient, *, file: str = _FILE) -> File:
    return await reader.sharepoint_read_file(client, file=file)


class TestWhatComesBack:
    async def test_a_word_file_comes_back_as_that_word_file(
        self, client: GraphServiceClient, item: respx.Route, content: respx.Route
    ) -> None:
        read = await _read(client)

        assert isinstance(read, File)
        assert read.data == _BYTES
        resource = read.to_resource_content().resource
        assert resource.mime_type == _DOCX
        assert resource.uri == f"file:///{_NAME}"
        assert (item.call_count, content.call_count) == (1, 1)

    @pytest.mark.usefixtures("content")
    async def test_it_asks_for_the_fields_every_drive_tool_agrees_on(
        self, client: GraphServiceClient, item: respx.Route
    ) -> None:
        _ = await _read(client)

        selected = item.calls.last.request.url.params["$select"]
        for field in ("name", "size", "file", "folder", "webUrl"):
            assert field in selected

    @pytest.mark.usefixtures("item")
    async def test_the_content_request_asks_for_no_conversion_at_all(
        self, client: GraphServiceClient, content: respx.Route
    ) -> None:
        _ = await _read(client)

        assert content.calls.last.request.url.params == httpx.QueryParams()

    @pytest.mark.usefixtures("content")
    async def test_a_media_type_graph_does_not_report_falls_back_to_plain_bytes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_payload(mime_type=None))
        )

        read = await _read(client)

        assert read.to_resource_content().resource.mime_type == "application/octet-stream"

    async def test_an_empty_file_comes_back_empty_rather_than_as_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=_payload(size=0)))
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=b""))

        read = await _read(client)

        assert read.data == b""
        assert read.to_resource_content().resource.mime_type == _DOCX


class TestWhatItRefuses:
    async def test_a_value_that_is_not_a_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="did not get a file handle"):
            _ = await _read(client, file="https://contoso.sharepoint.invalid/Quarterly.docx")

        assert graph.calls.call_count == 0

    async def test_a_folder_handle_is_refused_and_sent_to_the_browsing_tool(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="sharepoint_browse_folder") as refused:
            _ = await _read(client, file=_FOLDER)

        assert "A folder holds no content" in str(refused.value)
        assert graph.calls.call_count == 0

    async def test_an_item_graph_reports_as_a_folder_is_refused_before_any_content_is_asked_for(
        self, client: GraphServiceClient, graph: respx.MockRouter, content: respx.Route
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_payload(a_folder=True))
        )

        with pytest.raises(ToolError, match="a folder is not a file") as refused:
            _ = await _read(client)

        assert _FOLDER in str(refused.value), "the refusal hands over the handle that browses it"
        assert content.call_count == 0

    async def test_a_file_above_the_limit_is_refused_without_ever_being_fetched(
        self, client: GraphServiceClient, graph: respx.MockRouter, content: respx.Route
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_payload(size=reader.MAX_BYTES + 1))
        )

        with pytest.raises(ToolError):
            _ = await _read(client)

        assert content.call_count == 0, "the refusal cost one request, not two"

    async def test_the_size_refusal_says_the_size_the_limit_and_where_to_open_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_payload(size=31 * 1024 * 1024))
        )

        with pytest.raises(ToolError) as refused:
            _ = await _read(client)

        refusal = str(refused.value)
        assert "31.0 MB" in refusal
        assert "10.0 MB or less" in refusal
        assert "held in memory and sent to you in one message" in refusal
        assert _WEB_URL in refusal
        assert "never sends part of a file" in refusal

    async def test_a_large_file_without_a_web_address_is_still_refused_with_advice(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(200, json=_payload(size=reader.MAX_BYTES + 1, web_url=None))
        )

        with pytest.raises(ToolError, match="no web address") as refused:
            _ = await _read(client)

        assert "None" not in str(refused.value), "a missing address is described, never printed"

    async def test_a_file_graph_reports_no_size_for_is_refused_before_any_content_is_asked_for(
        self, client: GraphServiceClient, graph: respx.MockRouter, content: respx.Route
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=_payload(size=None)))

        with pytest.raises(ToolError, match="did not say how large") as refused:
            _ = await _read(client)

        assert content.call_count == 0, "an unknown size must not fall through to a download"
        assert "in one message" in str(refused.value)

    async def test_a_package_is_refused_because_it_is_neither_a_file_nor_a_folder(
        self, client: GraphServiceClient, graph: respx.MockRouter, content: respx.Route
    ) -> None:
        package = {
            "id": ITEM_ID,
            "name": "Team notebook",
            "size": 4096,
            "webUrl": _WEB_URL,
            "parentReference": {"driveId": DRIVE_ID},
            "package": {"type": "oneNote"},
        }
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=package))

        with pytest.raises(ToolError, match="not hold this item as a plain file"):
            _ = await _read(client)

        assert content.call_count == 0

    async def test_a_body_larger_than_the_limit_is_refused_even_when_graph_understated_its_size(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(return_value=httpx.Response(200, json=_payload(size=10)))
        _ = graph.get(_CONTENT_PATH).mock(
            return_value=httpx.Response(200, content=b"x" * (reader.MAX_BYTES + 1))
        )

        with pytest.raises(ToolError, match="sharepoint_read_file returns a file of"):
            _ = await _read(client)

    async def test_text_that_is_not_utf8_keeps_its_bytes_instead_of_being_decoded(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        utf16 = "name,value\r\n".encode("utf-16")
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(
                200, json=_payload(name="rows.csv", size=len(utf16), mime_type="text/csv")
            )
        )
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=utf16))

        answer = await _read(client)

        resource = answer.to_resource_content().resource

        assert isinstance(resource, BlobResourceContents), (
            "a text/* media type sends FastMCP down a decode path that never raises and corrupts"
        )
        assert base64.b64decode(resource.blob) == utf16, "the bytes must survive exactly"
        assert resource.mime_type == "application/octet-stream"

    async def test_text_that_is_utf8_keeps_the_media_type_graph_reported(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        plain = b"name,value\r\nalpha,1\r\n"
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(
                200, json=_payload(name="rows.csv", size=len(plain), mime_type="text/csv")
            )
        )
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=plain))

        answer = await _read(client)

        resource = answer.to_resource_content().resource

        assert isinstance(resource, TextResourceContents)
        assert resource.mime_type == "text/csv"
        assert resource.text == plain.decode("utf-8")

    @pytest.mark.usefixtures("item")
    async def test_no_bytes_for_a_file_that_holds_data_is_refused_rather_than_answered_empty(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=b""))

        with pytest.raises(ToolError, match="sent no content"):
            _ = await _read(client)

    async def test_a_file_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _read(client)


class TestWhatItCounts:
    @pytest.mark.usefixtures("item", "content")
    async def test_the_two_requests_are_counted_under_a_step_each(
        self, client: GraphServiceClient
    ) -> None:
        before = {
            step: _value(GRAPH_STEPS_TOTAL, operation=reader.TOOL_NAME, step=step, status="ok")
            for step in (reader.STEP_ITEM, reader.STEP_CONTENT)
        }

        _ = await _read(client)

        for step, counted in before.items():
            assert (
                _value(GRAPH_STEPS_TOTAL, operation=reader.TOOL_NAME, step=step, status="ok")
                == counted + 1
            ), step


class TestHowItDeclaresItself:
    def test_the_permission_is_the_read_one_microsoft_documents(self) -> None:
        assert reader.GRAPH_PERMISSIONS == ("Files.Read.All",)

    def test_each_graph_call_has_a_step_of_its_own(self) -> None:
        assert (reader.STEP_ITEM, reader.STEP_CONTENT) == ("drive_item", "drive_content")

    def test_the_refusable_call_is_a_handle_this_tool_accepts(self) -> None:
        assert set(reader.GRAPH_CALL_EXAMPLE) == {"file"}
        example = cast("str", reader.GRAPH_CALL_EXAMPLE["file"])
        assert drive_file_handle(example) is not None

    def test_the_cap_is_ten_binary_megabytes(self) -> None:
        assert reader.MAX_BYTES == 10 * 1024 * 1024

    def test_a_404_sends_the_caller_back_to_search_and_not_to_a_deleted_file(self) -> None:
        assert "sharepoint_search_files" in reader.GRAPH_NOT_FOUND
        assert "moved it to another drive" in reader.GRAPH_NOT_FOUND
        assert "do not retry it" in reader.GRAPH_NOT_FOUND

    async def test_it_takes_one_argument_and_it_is_the_handle(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"file"}
        assert parameters["required"] == ["file"]

    async def test_no_argument_offers_a_conversion_or_a_page_of_a_file(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        for word in ("format", "convert", "text", "page", "offset"):
            assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_reading_and_changing_nothing(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        reader.register(mcp, transport)

        tool = await mcp.get_tool(reader.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.title == "Read File"

    async def test_the_description_says_the_file_comes_back_as_itself(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        reader.register(mcp, transport)
        tool = await mcp.get_tool(reader.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"

        described = tool.description or ""

        assert "This tool converts nothing" in described
        assert "does not turn a document into text" in described
        assert "A Word file comes back as a Word file" in described
        assert "sharepoint_search_files" in described
        assert "sharepoint_browse_folder" in described

    async def test_the_answer_carries_the_file_and_no_schema_to_validate_it_against(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        reader.register(mcp, transport)

        tool = await mcp.get_tool(reader.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.output_schema is None


async def _registered(transport: httpx.AsyncClient) -> Mapping[str, object]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    reader.register(mcp, transport)
    tool = await mcp.get_tool(reader.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool.parameters


@pytest.fixture(autouse=True)
def metrics_provider() -> None:
    _ = configure_metrics(
        AppConfig.model_validate({"public_base_url": "https://office-365-mcp.example"})
    )


def _value(metric: str, **labels: str) -> float:
    wanted = frozenset(labels.items())
    matched = [value for keys, value in _samples(metric).items() if wanted <= keys]
    assert len(matched) <= 1, f"{metric}{labels} matched {len(matched)} series"
    return matched[0] if matched else 0.0


def _samples(metric: str) -> dict[frozenset[tuple[str, str]], float]:
    found: dict[frozenset[tuple[str, str]], float] = {}
    for line in generate_latest(REGISTRY).decode().splitlines():
        if line.startswith("#") or not line.startswith(metric):
            continue
        series, _, value = line.rpartition(" ")
        name, _, labels = series.partition("{")
        if name != metric:
            continue
        found[frozenset(_labels(labels.rstrip("}")))] = float(value)
    return found


def _labels(rendered: str) -> Iterator[tuple[str, str]]:
    for pair in rendered.split('",') if rendered else ():
        name, _, value = pair.partition("=")
        yield name.strip(), value.strip().strip('"')
