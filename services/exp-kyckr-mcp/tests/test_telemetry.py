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

from kyckr_mcp.client import KyckrApiError, raise_for_kyckr_error
from kyckr_mcp.telemetry import (
    credit_cost,
    record_upstream_call,
    route_template,
    start_upstream_call,
)


@pytest.fixture(scope="module")
def spans() -> Generator[InMemorySpanExporter, None, None]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter


def sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0


def call(handler: httpx2.MockTransport, method: str, path: str) -> None:
    async def run() -> None:
        async with httpx2.AsyncClient(
            base_url="https://test-api.kyckr.com/v2",
            transport=handler,
            event_hooks={
                "request": [start_upstream_call],
                "response": [record_upstream_call, raise_for_kyckr_error],
            },
        ) as client:
            with suppress(KyckrApiError):
                await client.request(method, path)

    asyncio.run(run())


def test_route_template_normalizes_ids() -> None:
    assert route_template("/v2/companies/GB%7Cabc/lite") == "/companies/:kyckrId/lite"
    assert route_template("/v2/orders/5/download") == "/orders/:orderId/download"
    assert route_template("/v2/nope") == "[unknown]"


def test_credit_cost_reads_top_level_then_data() -> None:
    assert credit_cost({"cost": {"value": 2}}) == 2
    assert credit_cost({"data": {"cost": {"value": 3}}}) == 3
    assert credit_cost({"data": []}) == 0


def test_paid_call_records_metrics_credits_and_span(spans: InMemorySpanExporter) -> None:
    labels = {"method": "GET", "path": "/companies/:kyckrId/lite"}
    before_requests = sample("kyckr_api_requests_total", {**labels, "status": "200"})
    before_credits = sample("kyckr_credits_consumed_total", labels)
    spans.clear()

    call(
        httpx2.MockTransport(lambda _r: httpx2.Response(200, json={"cost": {"value": 2}})),
        "GET",
        "/companies/GB%7Cabc/lite",
    )

    assert sample("kyckr_api_requests_total", {**labels, "status": "200"}) == before_requests + 1
    assert sample("kyckr_credits_consumed_total", labels) == before_credits + 2
    (span,) = spans.get_finished_spans()
    assert span.name == "GET /companies/:kyckrId/lite"
    assert span.attributes is not None
    assert span.attributes["http.response.status_code"] == 200


def test_error_call_marks_span_failed_and_costs_nothing(spans: InMemorySpanExporter) -> None:
    labels = {"method": "GET", "path": "/companies/:kyckrId/lite"}
    before_credits = sample("kyckr_credits_consumed_total", labels)
    spans.clear()

    call(
        httpx2.MockTransport(lambda _r: httpx2.Response(404, json={"cost": {"value": 2}})),
        "GET",
        "/companies/GB%7Cabc/lite",
    )

    assert sample("kyckr_api_requests_total", {**labels, "status": "404"}) >= 1
    assert sample("kyckr_credits_consumed_total", labels) == before_credits
    (span,) = spans.get_finished_spans()
    assert span.status.status_code == trace.StatusCode.ERROR
