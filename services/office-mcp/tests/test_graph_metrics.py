"""The Graph metrics, asserted on a scrape of the registry `/metrics` actually serves.

Trap: `configure_metrics` aims its Prometheus reader at `unique_toolkit.monitoring.REGISTRY`, not at
`prometheus_client`'s default one. A test that asked the default registry — or that only asked
whether `/metrics` answers 200 — would pass with every instrument in this service unbound, because
an empty registry answers 200 too. These tests read the same registry object the route reads.

Every assertion is a delta across the call rather than an absolute value: the registry is
process-wide and cumulative, and the rest of the suite drives the same tools under the same
operation names.
"""

from collections.abc import AsyncGenerator, Iterator

import httpx
import pytest
import respx
from kiota_http.middleware import retry_handler
from msgraph.graph_service_client import GraphServiceClient
from prometheus_client import generate_latest
from unique_toolkit.monitoring import REGISTRY

from office_mcp.config import AppConfig
from office_mcp.graph_client import (
    GRAPH_PAGES_SCANNED,
    GRAPH_REQUEST_DURATION_SECONDS,
    GRAPH_REQUESTS_TOTAL,
    GRAPH_THROTTLED_TOTAL,
    GraphForbidden,
    GraphSettings,
    GraphThrottled,
    create_graph_transport,
    graph_client_for,
    graph_errors,
)
from office_mcp.metrics import configure_metrics

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

CALLER_TOKEN = "synthetic-graph-access-token"

_ME = {"id": "00000000-0000-4000-8000-000000000001", "displayName": "Ada Lovelace"}


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


@pytest.fixture(autouse=True)
def metrics_provider() -> None:
    """The reader that binds this service's instruments to the toolkit registry.

    Idempotent and shared with every other test that builds the app, which is why it is not torn
    down: an OpenTelemetry meter provider can be installed once per process.
    """
    _ = configure_metrics(
        AppConfig.model_validate({"public_base_url": "https://office-mcp.example"})
    )


@pytest.fixture
def no_retry_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the SDK's retry handler decide to wait without a test waiting for it."""

    class _Instant:
        async def sleep(self, _delay: float) -> None:
            return None

    monkeypatch.setattr(retry_handler, "asyncio", _Instant())


def _samples(metric: str) -> dict[frozenset[tuple[str, str]], float]:
    """One scrape of the registry `/metrics` reads, as {labels: value} for one sample name."""
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


def _value(metric: str, **labels: str) -> float:
    """The one sample of `metric` carrying every label given, or 0 when there is none yet."""
    wanted = frozenset(labels.items())
    matched = [value for keys, value in _samples(metric).items() if wanted <= keys]
    assert len(matched) <= 1, f"{metric}{labels} matched {len(matched)} series"
    return matched[0] if matched else 0.0


class TestAGraphCallIsCountedAndTimed:
    async def test_a_call_shows_up_in_the_registry_the_metrics_route_scrapes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        before = _value(GRAPH_REQUESTS_TOTAL, operation="get_me", status="ok")
        timed = _value(f"{GRAPH_REQUEST_DURATION_SECONDS}_count", operation="get_me")

        with graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_REQUESTS_TOTAL, operation="get_me", status="ok") == before + 1
        assert _value(f"{GRAPH_REQUEST_DURATION_SECONDS}_count", operation="get_me") == timed + 1

    async def test_a_refusal_is_counted_under_its_remedy_and_not_its_status_code(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """403 and 401 are one remedy and 404 is another, which is what `errors.py` sorts them into.

        Counted by remedy rather than by code so that the series stay countable: the codes Graph can
        answer with are open-ended, and a dashboard panel per code is a panel nobody reads.
        """
        _ = graph.get("/me").mock(return_value=httpx.Response(403, json={}))
        before = _value(GRAPH_REQUESTS_TOTAL, operation="get_me", status="forbidden")

        with pytest.raises(GraphForbidden), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_REQUESTS_TOTAL, operation="get_me", status="forbidden") == before + 1

    async def test_a_call_nobody_named_is_not_counted_under_a_made_up_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """An `operation="unknown"` bucket reads on a dashboard as a real operation with real
        latency, and the tool that forgot to name itself disappears inside it. Nothing is recorded
        instead."""
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        before = _samples(GRAPH_REQUESTS_TOTAL)

        with graph_errors():
            _ = await client.me.get()

        assert _samples(GRAPH_REQUESTS_TOTAL) == before


class TestTheOperationLabelIsANameThisCodeChose:
    async def test_no_graph_series_carries_a_url_a_path_or_a_resource_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The one hazard these metrics could introduce. A label taken off a Graph URL is a new time
        series per chat, per message and per meeting — Graph URLs here are made of almost nothing
        else — and an unbounded label set takes the Prometheus down rather than showing up as a bad
        dashboard. `python_http_requests_total` already has this shape; these must not add to it."""
        chat_id = "19%3Aunbounded-cardinality%40thread.v2"
        _ = graph.get(f"/chats/{chat_id}").mock(return_value=httpx.Response(200, json={"id": "c"}))

        with graph_errors("list_chats"):
            _ = await client.chats.by_chat_id("19:unbounded-cardinality@thread.v2").get()

        families = (
            GRAPH_REQUESTS_TOTAL,
            f"{GRAPH_REQUEST_DURATION_SECONDS}_count",
            f"{GRAPH_PAGES_SCANNED}_count",
            GRAPH_THROTTLED_TOTAL,
        )
        values = {
            value
            for family in families
            for labels in _samples(family)
            for name, value in labels
            if name in ("operation", "status", "retried")
        }
        assert values, "no graph series was found at all, so this asserts over nothing"
        for value in values:
            assert "/" not in value, f"{value} looks like a path"
            assert "graph.microsoft.com" not in value
            assert "unbounded-cardinality" not in value


class TestThrottlingSaysWhetherTheSdkSpentItsRetries:
    @pytest.mark.usefixtures("no_retry_waiting")
    async def test_retries_spent_on_a_wait_the_sdk_was_willing_to_make(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A `Retry-After` under the SDK's ceiling: it waited, retried, and the quota was still
        gone. The remedy is quota, not patience."""
        graph.get("/me").mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}))
        before = _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="true")

        with pytest.raises(GraphThrottled), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="true") == before + 1

    @pytest.mark.usefixtures("no_retry_waiting")
    async def test_no_retry_attempted_when_graph_asked_for_a_wait_past_the_ceiling(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`RetryHandler` refuses a delay at or past 180 s, so this 429 was never retried at all —
        the answer is available later, which is the opposite remedy to the case above."""
        graph.get("/me").mock(return_value=httpx.Response(429, headers={"Retry-After": "600"}))
        before = _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="false")

        with pytest.raises(GraphThrottled), graph_errors("get_me"):
            _ = await client.me.get()

        assert _value(GRAPH_THROTTLED_TOTAL, operation="get_me", retried="false") == before + 1
