"""Every response body here is synthesised. None came from a real tenant."""

from collections.abc import AsyncGenerator, Iterator

import httpx
import pytest
import respx
from kiota_http.middleware import retry_handler
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import GraphSettings, create_graph_transport, graph_client_for

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

CALLER_TOKEN = "synthetic-graph-access-token"


@pytest.fixture
def graph() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def transport() -> AsyncGenerator[httpx.AsyncClient]:
    client = create_graph_transport(GraphSettings())
    yield client
    await client.aclose()


@pytest.fixture
def client(transport: httpx.AsyncClient) -> GraphServiceClient:
    return graph_client_for(transport, CALLER_TOKEN)


class RecordedSleeps:
    """Stands in for the `asyncio` module inside the SDK's retry handler, which only calls
    `await asyncio.sleep(delay)`. Patching `asyncio.sleep` globally would slow everything else on
    the loop."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)


@pytest.fixture
def retry_sleeps(monkeypatch: pytest.MonkeyPatch) -> RecordedSleeps:
    recorded = RecordedSleeps()
    monkeypatch.setattr(retry_handler, "asyncio", recorded)
    return recorded
