import logging

import pytest
from fastmcp import Client
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from mcp_observability import MetricNamespace
from mcp_observability import metrics_text
from mcp_observability import setup_ops


@pytest.fixture
def server() -> FastMCP:
    mcp = FastMCP(name="Kiosk")

    @mcp.tool
    def greet(name: str) -> str:
        """Greet someone."""
        return f"hello {name}"

    @mcp.tool
    def fail() -> str:
        """Always fails."""
        raise ToolError("no")

    @mcp.tool
    def crash() -> str:
        """Always breaks."""
        raise RuntimeError("bug")

    return mcp


@pytest.fixture
def client(server: FastMCP) -> TestClient:
    middleware = setup_ops(server)
    return TestClient(server.http_app(transport="streamable-http", middleware=[middleware]))


@pytest.mark.parametrize(("path", "status"), [("/probe", "ok"), ("/health", "healthy")])
def test_the_probes_answer(client: TestClient, path: str, status: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.json() == {"status": status}


def test_metrics_count_http_requests_but_not_the_ops_routes(client: TestClient) -> None:
    client.get("/probe")
    client.get("/missing")

    text = client.get("/metrics").text

    assert 'python_http_requests_total{method="GET",path="/missing",status_code="404"}' in text
    assert 'path="/probe"' not in text
    assert "text/plain" in client.get("/metrics").headers["content-type"]


async def test_every_tool_call_is_counted_with_its_outcome(server: FastMCP) -> None:
    setup_ops(server)

    async with Client(server) as client:
        await client.call_tool("greet", {"name": "Ada"})
        with pytest.raises(ToolError):
            await client.call_tool("fail", {})

    text = metrics_text().decode()
    assert 'mcp_calls_total{kind="tool",name="greet",status="ok"}' in text
    assert 'mcp_calls_total{kind="tool",name="fail",status="ToolError"}' in text
    assert 'mcp_call_duration_seconds_count{kind="tool",name="greet"}' in text


async def test_a_failed_call_is_logged_once_with_its_exception_out_of_the_message(
    server: FastMCP, caplog: pytest.LogCaptureFixture
) -> None:
    setup_ops(server)

    with caplog.at_level(logging.INFO):
        async with Client(server) as client:
            await client.call_tool("fail", {}, raise_on_error=False)
            await client.call_tool("crash", {}, raise_on_error=False)

    outcomes = [
        (record.levelno, record.getMessage(), record.exc_info is not None)
        for record in caplog.records
        if record.name == "mcp_observability"
    ]
    assert outcomes == [
        (logging.WARNING, "tool 'fail' failed", True),
        (logging.WARNING, "tool 'crash' failed", True),
    ]


def test_a_metric_of_the_mcps_own_is_served_under_its_prefix() -> None:
    MetricNamespace("kiosk").counter("visits_total", "Visits", ["door"]).labels(door="front").inc()

    assert 'kiosk_visits_total{door="front"} 1.0' in metrics_text().decode()
