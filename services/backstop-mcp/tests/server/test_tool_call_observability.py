"""One start line and one terminal line per tool call, with no argument values."""

import logging
import re
from collections.abc import Iterator, Mapping
from typing import Protocol, cast

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from mcp.server.auth.provider import AccessToken
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from pydantic import HttpUrl
from starlette.testclient import TestClient
from unique_mcp.monitoring import setup_ops
from unique_toolkit.monitoring import get_metrics

from backstop_mcp.config import AppConfig
from backstop_mcp.logging import configure_logging
from backstop_mcp.observability import add_call_fields
from backstop_mcp.server.tool_call_observability import ToolCallObservabilityMiddleware
from tests.helpers import assert_absent_from_records

_EMAIL = "jane@example.com"
_SUBJECT = "6f1c2a3e-0d4b-4e8f-9a7c-1b2d3e4f5a6b"
_ECHO_CALLS = re.compile(r'^mcp_calls_total\{[^}]*name="echo_email"[^}]*\} (\S+)$', re.MULTILINE)


class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    @property
    def text(self) -> str: ...


def _build_server() -> FastMCP:
    configure_logging(AppConfig(public_base_url=HttpUrl("https://backstop-mcp.example")))
    server = FastMCP("observability-probe", middleware=[ToolCallObservabilityMiddleware()])
    setup_ops(server)

    @server.tool
    async def echo_email(email: str) -> str:
        add_call_fields(returned=3 if email else 0)
        return "ok"

    @server.tool
    async def missing_user() -> str:
        raise ToolError(f"No user {_EMAIL!r}")

    @server.tool
    async def boom() -> str:
        raise KeyError("missing")

    @server.tool
    async def needs_count(count: int) -> str:
        return str(count)

    return server


def _records(caplog: pytest.LogCaptureFixture, message: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.message == message]


def _echo_calls() -> float:
    values = cast("list[str]", _ECHO_CALLS.findall(get_metrics().decode()))
    return sum(float(value) for value in values)


def _post(client: TestClient, body: dict[str, object], headers: Mapping[str, str]) -> _HttpResponse:
    return cast("_HttpResponse", client.post("/mcp", json=body, headers=dict(headers)))


@pytest.fixture
def server() -> FastMCP:
    return _build_server()


class TestToolCallLog:
    async def test_success_logs_start_and_completed(
        self, server: FastMCP, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)

        async with Client(server) as client:
            await client.call_tool("echo_email", {"email": _EMAIL})

        started = _records(caplog, "tool.call.start")
        completed = _records(caplog, "tool.call.completed")
        assert len(started) == 1
        assert len(completed) == 1
        assert started[0].levelno == logging.INFO
        assert completed[0].tool == "echo_email"  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        assert completed[0].argument_names == ["email"]  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        assert completed[0].returned == 3  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        assert completed[0].duration_ms >= 0  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        assert_absent_from_records(caplog, _EMAIL)

    async def test_tool_error_is_a_warning_without_the_message_or_a_traceback(
        self, server: FastMCP, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)

        async with Client(server) as client:
            with pytest.raises(ToolError):
                await client.call_tool("missing_user", {})

        failed = _records(caplog, "tool.call.failed")
        assert len(failed) == 1
        assert failed[0].levelno == logging.WARNING
        assert failed[0].error_type == "ToolError"  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        assert failed[0].exc_info is None
        assert_absent_from_records(caplog, _EMAIL)

    async def test_a_bug_is_an_error_with_a_traceback(
        self, server: FastMCP, caplog: pytest.LogCaptureFixture, exporter: InMemorySpanExporter
    ) -> None:
        caplog.set_level(logging.INFO)

        async with Client(server) as client:
            with pytest.raises(ToolError):
                await client.call_tool("boom", {})

        failed = _records(caplog, "tool.call.failed")
        assert len(failed) == 1
        assert failed[0].levelno == logging.ERROR
        assert failed[0].exc_info is not None
        span = next(
            item for item in exporter.get_finished_spans() if item.name == "tools/call boom"
        )
        assert span.status.status_code == StatusCode.ERROR

    async def test_invalid_arguments_log_locations_only(
        self, server: FastMCP, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)

        async with Client(server) as client:
            with pytest.raises(ToolError):
                await client.call_tool("needs_count", {"count": _EMAIL})

        failed = _records(caplog, "tool.call.failed")
        assert len(failed) == 1
        assert failed[0].levelno == logging.WARNING
        assert failed[0].invalid_arguments == ["count"]  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        assert_absent_from_records(caplog, _EMAIL)

    async def test_metrics_still_count_the_call(self, server: FastMCP) -> None:
        before = _echo_calls()

        async with Client(server) as client:
            await client.call_tool("echo_email", {"email": _EMAIL})

        assert _echo_calls() == before + 1

    async def test_the_subject_is_on_every_line(
        self, server: FastMCP, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token = AccessToken(token="opaque", client_id="client", scopes=[], subject=_SUBJECT)
        monkeypatch.setattr(
            "backstop_mcp.server.tool_call_observability.get_access_token", lambda: token
        )
        caplog.set_level(logging.INFO)

        async with Client(server) as client:
            await client.call_tool("echo_email", {"email": _EMAIL})

        for message in ("tool.call.start", "tool.call.completed"):
            (record,) = _records(caplog, message)
            assert record.subject == _SUBJECT  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


class TestToolCallSpan:
    @pytest.fixture
    def spans(self, exporter: InMemorySpanExporter) -> Iterator[list[ReadableSpan]]:
        server = _build_server()
        app = server.http_app()
        with TestClient(app) as client:
            exporter.clear()
            headers = {
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            }
            initialize = _post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
                headers,
            )
            assert initialize.status_code == 200, initialize.text
            session = initialize.headers["mcp-session-id"]
            headers = {**headers, "mcp-session-id": session}
            _post(
                client,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers,
            )
            called = _post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "echo_email", "arguments": {"email": _EMAIL}},
                },
                headers,
            )
            assert called.status_code == 200, called.text
        yield [
            span for span in exporter.get_finished_spans() if span.name == "tools/call echo_email"
        ]

    def test_the_span_carries_argument_names_and_both_events(
        self, spans: list[ReadableSpan]
    ) -> None:
        assert len(spans) == 1
        span = spans[0]
        assert span.attributes is not None
        argument_names = span.attributes["argument_names"]
        assert isinstance(argument_names, tuple | list)
        assert list(argument_names) == ["email"]
        assert span.attributes["returned"] == 3
        names = [event.name for event in span.events]
        assert "tool.call.start" in names
        assert "tool.call.completed" in names
        rendered = str(span.attributes) + str([event.attributes for event in span.events])
        assert _EMAIL not in rendered
