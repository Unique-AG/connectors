from collections.abc import Iterator

import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient

from mcp_runtime import ServerSettings, http_app, instrument


@pytest.fixture
def client() -> Iterator[TestClient]:
    mcp = FastMCP(name="Probe")
    app = http_app(mcp, ServerSettings(), [instrument(mcp)])
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("path", ["/probe", "/health", "/metrics"])
def test_instrument_mounts_the_ops_routes(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200
