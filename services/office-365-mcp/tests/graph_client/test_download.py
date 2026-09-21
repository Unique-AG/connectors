"""`download_to_file`: the spool file, the error-body bound, the size guards. Data is synthetic."""

import asyncio
import gzip
from collections.abc import AsyncIterator
from pathlib import Path
from typing import override

import httpx
import pytest
import respx
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.request_information import RequestInformation
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import (
    GraphForbidden,
    GraphNotFound,
    GraphResponseTooLarge,
    GraphUnavailable,
    download_to_file,
    graph_errors,
)

_MESSAGE_ID = "AAMkAGI2SYNTHETIC-immutable-0001="

_PATH = "/me/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D/$value"

_BODY = b"Subject: Invoice 4471\r\n\r\nThe invoice never arrived.\r\n"

_MAX_BYTES = 1024 * 1024

_PAST_THE_ERROR_BOUND = 128 * 1024

_OPERATION = "synthetic_download"


def _request_info(client: GraphServiceClient) -> RequestInformation:
    return client.me.messages.by_message_id(_MESSAGE_ID).content.to_get_request_information(
        RequestConfiguration[QueryParameters]()
    )


def _odata(code: str, padding: int = 0) -> bytes:
    """A Graph error document, optionally padded."""
    return b'{"error":{"code":"' + code.encode() + b'","message":"' + b"x" * padding + b'"}}'


class _Slowly(httpx.AsyncByteStream):
    """A body that arrives in pieces, so a cancellation can land in the middle of one."""

    def __init__(self, chunks: list[bytes], *, pause: float = 0.0) -> None:
        self.chunks: list[bytes] = chunks
        self.pause: float = pause
        self.delivered: int = 0

    @override
    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            if self.pause:
                await asyncio.sleep(self.pause)
            self.delivered += 1
            yield chunk


def _spool(tmp_path: Path) -> Path:
    directory = tmp_path / "spool"
    directory.mkdir()
    return directory


class TestTheSpoolFileNeverOutlivesTheBlock:
    """Every exit from this context manager is its own way to leak a file."""

    async def test_the_directory_is_empty_after_a_download_that_succeeded(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        tmp_path: Path,
    ) -> None:
        _ = graph.get(_PATH).mock(return_value=httpx.Response(200, content=_BODY))
        directory = _spool(tmp_path)

        async with download_to_file(
            client, transport, _request_info(client), directory=directory, max_bytes=_MAX_BYTES
        ) as downloaded:
            assert downloaded.path.read_bytes() == _BODY
            assert list(directory.iterdir()) == [downloaded.path], (
                "the body is spooled to exactly one file while the block is open"
            )

        assert list(directory.iterdir()) == []

    async def test_the_directory_is_empty_after_a_refusal_on_the_declared_length(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        tmp_path: Path,
    ) -> None:
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                200, stream=_Slowly([_BODY]), headers={"Content-Length": str(_MAX_BYTES + 1)}
            )
        )
        directory = _spool(tmp_path)

        with pytest.raises(GraphResponseTooLarge):
            async with download_to_file(
                client, transport, _request_info(client), directory=directory, max_bytes=_MAX_BYTES
            ):
                pass

        assert list(directory.iterdir()) == []

    async def test_the_directory_is_empty_after_a_refusal_on_the_bytes_written(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        tmp_path: Path,
    ) -> None:
        """The one that has already written to the file when it raises."""
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(200, stream=_Slowly([b"x" * (_MAX_BYTES + 1)]))
        )
        directory = _spool(tmp_path)

        with pytest.raises(GraphResponseTooLarge):
            async with download_to_file(
                client, transport, _request_info(client), directory=directory, max_bytes=_MAX_BYTES
            ):
                pass

        assert list(directory.iterdir()) == []

    async def test_the_directory_is_empty_after_a_body_that_stopped_short(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        tmp_path: Path,
    ) -> None:
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                200, stream=_Slowly([_BODY]), headers={"Content-Length": str(len(_BODY) + 4096)}
            )
        )
        directory = _spool(tmp_path)

        with pytest.raises(GraphUnavailable):
            async with download_to_file(
                client, transport, _request_info(client), directory=directory, max_bytes=_MAX_BYTES
            ):
                pass

        assert list(directory.iterdir()) == []

    async def test_the_directory_is_empty_after_graph_refused_the_read(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        tmp_path: Path,
    ) -> None:
        """No file is ever opened on this path."""
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                403,
                content=_odata("ErrorAccessDenied"),
                headers={"Content-Type": "application/json"},
            )
        )
        directory = _spool(tmp_path)

        with pytest.raises(GraphForbidden), graph_errors(_OPERATION):
            async with download_to_file(
                client, transport, _request_info(client), directory=directory, max_bytes=_MAX_BYTES
            ):
                pass

        assert list(directory.iterdir()) == []

    async def test_the_directory_is_empty_after_the_caller_raised_inside_the_block(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        tmp_path: Path,
    ) -> None:
        """The caller reads the file inside the block, so the caller is a way for it to leak."""
        _ = graph.get(_PATH).mock(return_value=httpx.Response(200, content=_BODY))
        directory = _spool(tmp_path)

        with pytest.raises(ZeroDivisionError):
            async with download_to_file(
                client, transport, _request_info(client), directory=directory, max_bytes=_MAX_BYTES
            ):
                _ = 1 // 0

        assert list(directory.iterdir()) == []

    async def test_the_directory_is_empty_after_the_download_was_cancelled(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        tmp_path: Path,
    ) -> None:
        """`CancelledError` inherits from `BaseException`, not `Exception`."""
        body = _Slowly([b"x" * 4096] * 64, pause=0.01)
        _ = graph.get(_PATH).mock(return_value=httpx.Response(200, stream=body))
        directory = _spool(tmp_path)

        async def download() -> None:
            async with download_to_file(
                client, transport, _request_info(client), directory=directory, max_bytes=_MAX_BYTES
            ):
                pass

        task = asyncio.create_task(download())
        while body.delivered < 2:
            await asyncio.sleep(0.005)
        _ = task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert list(directory.iterdir()) == []


class TestAFailureIsClassifiedByWhatGraphSaidAboutIt:
    """The bound on how much of an error body is read is the hazard here."""

    @pytest.mark.parametrize(
        ("status", "failure"),
        [(403, GraphForbidden), (404, GraphNotFound), (500, GraphUnavailable)],
        ids=repr,
    )
    async def test_an_error_document_that_fits_is_classified_with_its_odata_code(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        tmp_path: Path,
        status: int,
        failure: type[Exception],
    ) -> None:
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                status,
                content=_odata("ErrorItemNotFound"),
                headers={"Content-Type": "application/json"},
            )
        )

        with pytest.raises(failure) as raised, graph_errors(_OPERATION):
            async with download_to_file(
                client,
                transport,
                _request_info(client),
                directory=_spool(tmp_path),
                max_bytes=_MAX_BYTES,
            ):
                pass

        assert "ErrorItemNotFound" in str(raised.value)

    @pytest.mark.parametrize(
        ("status", "failure"),
        [(403, GraphForbidden), (404, GraphNotFound), (500, GraphUnavailable)],
        ids=repr,
    )
    async def test_an_error_document_past_the_bound_is_still_classified_by_its_status(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        tmp_path: Path,
        status: int,
        failure: type[Exception],
    ) -> None:
        """The OData code is lost, and that is the trade this makes on purpose."""
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                status,
                content=_odata("ErrorItemNotFound", padding=_PAST_THE_ERROR_BOUND),
                headers={"Content-Type": "application/json"},
            )
        )

        with pytest.raises(failure), graph_errors(_OPERATION):
            async with download_to_file(
                client,
                transport,
                _request_info(client),
                directory=_spool(tmp_path),
                max_bytes=_MAX_BYTES,
            ):
                pass


class TestTheSizeGuardsMeasureTheQuantityTheyGuard:
    """`Content-Length` counts wire bytes and `aiter_bytes` yields decoded ones."""

    async def test_a_content_coded_body_that_arrived_whole_is_not_called_truncated(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        tmp_path: Path,
    ) -> None:
        """Compression that expands rather than shrinks breaks a naive check."""
        coded = gzip.compress(_BODY)
        assert len(coded) > len(_BODY), "this body has to expand for the test to mean anything"
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                200,
                stream=_Slowly([coded]),
                headers={"Content-Encoding": "gzip", "Content-Length": str(len(coded))},
            )
        )

        async with download_to_file(
            client,
            transport,
            _request_info(client),
            directory=_spool(tmp_path),
            max_bytes=_MAX_BYTES,
        ) as downloaded:
            assert downloaded.path.read_bytes() == _BODY
            assert downloaded.size == len(_BODY), "size is what the caller holds, decoded"

    async def test_the_ceiling_is_enforced_against_the_bytes_a_caller_would_hold(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        tmp_path: Path,
    ) -> None:
        """A body that fits compressed and does not fit decoded."""
        oversized = b"x" * (_MAX_BYTES + 1)
        coded = gzip.compress(oversized)
        assert len(coded) < _MAX_BYTES, "a compressible body is the point of this test"
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                200,
                stream=_Slowly([coded]),
                headers={"Content-Encoding": "gzip", "Content-Length": str(len(coded))},
            )
        )

        with pytest.raises(GraphResponseTooLarge) as refusal:
            async with download_to_file(
                client,
                transport,
                _request_info(client),
                directory=_spool(tmp_path),
                max_bytes=_MAX_BYTES,
            ):
                pass

        assert refusal.value.size is not None, "the header could not have refused this one"
