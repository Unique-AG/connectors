"""A mocked graph.microsoft.com, and a Graph client that calls it as a synthetic user.

The other test directories build the same three fixtures. They are duplicated here rather than
imported across, so that `shared/` is tested against `shared/` alone and no test package depends
on another one's fixtures.

Every payload in this directory is invented: the ids are fake, the domains are `.invalid`, and
the names are from the public domain.
"""

from collections.abc import AsyncGenerator, Iterator

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import GraphSettings, create_graph_transport, graph_client_for

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

# What FastMCP's On-Behalf-Of exchange would have returned. Only its identity matters.
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
