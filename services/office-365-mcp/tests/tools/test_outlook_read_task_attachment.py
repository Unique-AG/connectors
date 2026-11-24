from base64 import b64decode
from collections.abc import Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from mcp.types import BlobResourceContents, TextResourceContents
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.shared.files import MAX_BYTES
from office_365_mcp.shared.seam import FileFromGraph
from office_365_mcp.tools.outlook_read_task_attachment import read_task_attachment

_LIST_ID = "AAMkSYNTHETIClist0001"
_TASK_ID = "AAMkSYNTHETICtask0001"
_FILE_ID = "AAMkSYNTHETICattachment0001"
_TASK = f"outlook:///tasks/{_LIST_ID}/{_TASK_ID}"
_FILE = f"{_TASK}/attachments/{_FILE_ID}"
_ONE_FILE = f"/me/todo/lists/{_LIST_ID}/tasks/{_TASK_ID}/attachments/{_FILE_ID}"
_CONTENT = f"{_ONE_FILE}/$value"
_PDF = b"%PDF-1.7\n\x00\xff synthetic"


def _described(
    graph: respx.MockRouter, *, name: str, content_type: str, size: int | None
) -> respx.Route:
    described: dict[str, object] = {
        "@odata.type": "#microsoft.graph.taskFileAttachment",
        "id": _FILE_ID,
        "name": name,
        "contentType": content_type,
    }
    if size is not None:
        described["size"] = size
    return graph.get(_ONE_FILE).mock(return_value=httpx.Response(200, json=described))


def _content(graph: respx.MockRouter, body: bytes, content_type: str) -> respx.Route:
    return graph.get(_CONTENT).mock(
        return_value=httpx.Response(200, content=body, headers={"Content-Type": content_type})
    )


async def _read(client: GraphServiceClient, attachment: str = _FILE) -> FileFromGraph:
    answer = await read_task_attachment(client, attachment=attachment)
    assert isinstance(answer, FileFromGraph)
    return answer


class TestTheFileThatComesBack:
    async def test_a_text_file_comes_back_as_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        text = b"Venue: Hall B\nBudget: 4000 CHF\n"
        described = _described(graph, name="Notes.txt", content_type="text/plain", size=len(text))
        _ = _content(graph, text, "text/plain")

        answer = await _read(client)

        sent = answer.to_resource_content().resource
        assert isinstance(sent, TextResourceContents)
        assert (sent.text, sent.uri, sent.mime_type) == (
            text.decode(),
            "file:///Notes.txt",
            "text/plain",
        )
        assert described.calls.last.request.url.params["$select"] == "id,name,contentType,size"

    async def test_a_binary_file_comes_back_with_its_bytes_and_its_type(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _described(graph, name="Agenda.pdf", content_type="application/pdf", size=len(_PDF))
        _ = _content(graph, _PDF, "application/pdf")

        answer = await _read(client)

        sent = answer.to_resource_content().resource
        assert isinstance(sent, BlobResourceContents)
        assert (b64decode(sent.blob), sent.uri, sent.mime_type) == (
            _PDF,
            "file:///Agenda.pdf",
            "application/pdf",
        )

    async def test_a_text_type_on_bytes_that_are_not_utf8_comes_back_as_binary(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _described(graph, name="Odd.txt", content_type="text/plain", size=len(_PDF))
        _ = _content(graph, _PDF, "text/plain")

        answer = await _read(client)

        assert answer.mime_type == "application/octet-stream"

    async def test_an_empty_file_comes_back_empty(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _described(graph, name="Empty.txt", content_type="text/plain", size=0)
        _ = _content(graph, b"", "text/plain")

        answer = await _read(client)

        assert answer.data == b""


class TestWhatItRefuses:
    async def test_a_file_that_is_too_large_is_refused_before_the_download(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _described(graph, name="Big.zip", content_type="application/zip", size=MAX_BYTES + 1)
        download = _content(graph, b"never", "application/zip")

        with pytest.raises(ToolError, match="10.0 MB or less"):
            _ = await _read(client)

        assert download.call_count == 0

    async def test_a_file_with_no_size_is_refused_before_the_download(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _described(graph, name="Odd.bin", content_type="application/octet-stream", size=None)
        download = _content(graph, b"never", "application/octet-stream")

        with pytest.raises(ToolError, match="did not say how large"):
            _ = await _read(client)

        assert download.call_count == 0

    async def test_a_file_that_holds_data_but_sends_none_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _described(graph, name="Agenda.pdf", content_type="application/pdf", size=1024)
        _ = _content(graph, b"", "application/pdf")

        with pytest.raises(ToolError, match="sent no content"):
            _ = await _read(client)

    @pytest.mark.parametrize(
        "attachment",
        [_TASK, f"{_TASK}/links/{_FILE_ID}", "Agenda.pdf", f"outlook:///tasklists/{_LIST_ID}"],
    )
    async def test_a_handle_that_is_not_a_file_is_refused_before_any_call(
        self, client: GraphServiceClient, graph: respx.MockRouter, attachment: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook_read_task"):
            _ = await _read(client, attachment)

        assert cast("Sequence[Call]", graph.calls) == []
