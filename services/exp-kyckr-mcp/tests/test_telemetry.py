import asyncio
from collections.abc import Generator
from contextlib import suppress

import httpx2
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from unique_toolkit.monitoring import REGISTRY

from kyckr_mcp.client import KyckrApiError, create_client
from kyckr_mcp.settings import Settings
from kyckr_mcp.telemetry import credit_cost, route_template

LITE = {"method": "GET", "path": "/companies/:kyckrId/lite"}


@pytest.fixture(scope="module")
def spans() -> Generator[InMemorySpanExporter, None, None]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter


def sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0


def call(settings: Settings, status: int, body: object, method: str, path: str) -> None:
    transport = httpx2.MockTransport(lambda _request: httpx2.Response(status, json=body))

    async def run() -> None:
        async with create_client(settings, transport) as client:
            with suppress(KyckrApiError):
                await client.request(method, path)

    asyncio.run(run())


@pytest.mark.parametrize(
    ("path", "route"),
    [
        ("/v2/companies", "/companies"),
        ("/v2/companies/GB%7Cabc/lite", "/companies/:kyckrId/lite"),
        ("/v2/companies/GB%7Cabc/enhanced", "/companies/:kyckrId/enhanced"),
        ("/v2/companies/GB%7Cabc/documents", "/companies/:kyckrId/documents"),
        ("/v2/orders", "/orders"),
        ("/v2/orders/5", "/orders/:orderId"),
        ("/v2/orders/5/download", "/orders/:orderId/download"),
        ("/v2/nope", "[unknown]"),
    ],
)
def test_route_template_normalizes_ids(path: str, route: str) -> None:
    assert route_template(path) == route


def test_credit_cost_reads_the_top_level_before_data() -> None:
    assert credit_cost({"cost": {"value": 2}}) == 2
    assert credit_cost({"data": {"cost": {"value": 3}}}) == 3
    assert credit_cost({"cost": {"value": 2}, "data": {"cost": {"value": 3}}}) == 2
    assert credit_cost({"data": []}) == 0


def test_paid_call_records_metrics_credits_and_span(
    settings: Settings, spans: InMemorySpanExporter
) -> None:
    before_requests = sample("kyckr_api_requests_total", {**LITE, "status": "200"})
    before_credits = sample("kyckr_credits_consumed_total", LITE)
    spans.clear()

    call(settings, 200, {"cost": {"value": 2}}, "GET", "/companies/GB%7Cabc/lite")

    assert sample("kyckr_api_requests_total", {**LITE, "status": "200"}) == before_requests + 1
    assert sample("kyckr_credits_consumed_total", LITE) == before_credits + 2
    (span,) = spans.get_finished_spans()
    assert span.name == "GET /companies/:kyckrId/lite"
    assert span.attributes is not None
    assert span.attributes["http.response.status_code"] == 200


@pytest.mark.parametrize(
    ("method", "path", "labels"),
    [
        (
            "GET",
            "/companies/GB%7Cabc/enhanced",
            {"method": "GET", "path": "/companies/:kyckrId/enhanced"},
        ),
        ("POST", "/orders", {"method": "POST", "path": "/orders"}),
    ],
)
def test_the_other_paid_calls_count_credits(
    settings: Settings, method: str, path: str, labels: dict[str, str]
) -> None:
    before = sample("kyckr_credits_consumed_total", labels)

    call(settings, 200, {"cost": {"value": 4}}, method, path)

    assert sample("kyckr_credits_consumed_total", labels) == before + 4


def test_a_free_call_does_not_count_credits(settings: Settings) -> None:
    labels = {"method": "GET", "path": "/companies"}
    before = sample("kyckr_credits_consumed_total", labels)

    call(settings, 200, {"cost": {"value": 4}}, "GET", "/companies")

    assert sample("kyckr_credits_consumed_total", labels) == before


def test_error_call_marks_span_failed_and_costs_nothing(
    settings: Settings, spans: InMemorySpanExporter
) -> None:
    before_requests = sample("kyckr_api_requests_total", {**LITE, "status": "404"})
    before_credits = sample("kyckr_credits_consumed_total", LITE)
    spans.clear()

    call(settings, 404, {"cost": {"value": 2}}, "GET", "/companies/GB%7Cabc/lite")

    assert sample("kyckr_api_requests_total", {**LITE, "status": "404"}) == before_requests + 1
    assert sample("kyckr_credits_consumed_total", LITE) == before_credits
    (span,) = spans.get_finished_spans()
    assert span.status.status_code == trace.StatusCode.ERROR
