from collections.abc import Callable, Iterator
import contextlib
import json
import logging
import math
import time

import httpx2
from mcp_observability import REGISTRY
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from opentelemetry.trace import StatusCode
import pytest

from kyckr_mcp.upstream import upstream_http
from kyckr_mcp.upstream import UpstreamSettings
from tests.conftest import CallTool
from tests.conftest import FakeKyckr

type Handler = Callable[[httpx2.Request], httpx2.Response]

LITE = "/companies/:kyckrId/lite"
UPSTREAM_LOGGER = "kyckr_mcp.upstream.recording"
SECRETS = ("dummy-api-key", "GB%7C12345678", "12345678", "J40")


def sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0


def requests_total(method: str, path: str, status: str) -> float:
    return sample("kyckr_api_requests_total", {"method": method, "path": path, "status": status})


def retries_total(method: str, path: str) -> float:
    return sample("kyckr_api_retries_total", {"method": method, "path": path})


def kyckr_label_values(metric_name: str = "kyckr_") -> list[str]:
    return [
        value
        for metric in REGISTRY.collect()
        if metric.name.startswith(metric_name)
        for s in metric.samples
        for value in s.labels.values()
    ]


def credits_of(tool: str) -> float:
    return sample("kyckr_credits_consumed_total", {"tool": tool})


def all_credits() -> dict[str, float]:
    return {
        s.labels["tool"]: s.value
        for metric in REGISTRY.collect()
        for s in metric.samples
        if s.name == "kyckr_credits_consumed_total"
    }


async def get(
    settings: UpstreamSettings, handler: Handler, url: str, *, method: str = "GET"
) -> httpx2.Response | None:
    async with upstream_http(settings, httpx2.MockTransport(handler)) as client:
        try:
            return await client.request(method, url)
        except httpx2.HTTPError:
            return None


def upstream_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == UPSTREAM_LOGGER]


def answering(status: int, body: object = None) -> Handler:
    return lambda _: httpx2.Response(status, json=body if body is not None else {})


def time_out(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectTimeout("timed out", request=request)


def explode(request: httpx2.Request) -> httpx2.Response:
    raise RuntimeError(f"failed for {request.url} with dummy-api-key")


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    """The tracer provider is process-wide and settable once, so each test attaches an exporter
    to it and shuts that exporter down after.
    """
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter
    exporter.shutdown()


@pytest.mark.parametrize(
    ("path", "route"),
    [
        ("/companies", "/companies"),
        ("/companies/GB%7C12345678/lite", LITE),
        ("/companies/RO%7CJ40%2F8%2F1993/lite", LITE),
        ("/companies/GB%7C12345678/enhanced", "/companies/:kyckrId/enhanced"),
        ("/companies/GB%7C12345678/documents", "/companies/:kyckrId/documents"),
        ("/orders", "/orders"),
        ("/orders/9876", "/orders/:orderId"),
        ("/orders/9876/download", "/orders/:orderId/download"),
        ("/unlisted/9876", "[unknown]"),
    ],
)
async def test_the_path_label_replaces_registry_ids_with_placeholders(
    upstream_settings: UpstreamSettings, path: str, route: str
) -> None:
    before = requests_total("GET", route, "200")

    await get(upstream_settings, answering(200), path)

    assert requests_total("GET", route, "200") == before + 1


@pytest.mark.parametrize(
    "path",
    [
        "/companies/GB%7C12345678/orders",
        "/archive/orders",
        "/orders/9876/download/more",
        "/companies/lite",
        "/companies/GB%7C1/lite/extra",
    ],
)
async def test_a_lookalike_path_is_labelled_unknown(
    upstream_settings: UpstreamSettings, path: str
) -> None:
    before = requests_total("GET", "[unknown]", "200")

    await get(upstream_settings, answering(200), path)

    assert requests_total("GET", "[unknown]", "200") == before + 1


@pytest.mark.parametrize("value", [-1, -0.5, 0, True, False, math.nan, math.inf, "4", None])
async def test_a_cost_the_counter_rejects_does_not_fail_the_paid_call(
    upstream_settings: UpstreamSettings, value: object
) -> None:
    before = credits_of("create_document_order")

    # httpx2 refuses to encode NaN and Infinity, and json.dumps writes them.
    body = json.dumps({"cost": {"value": value}}).encode()
    response = await get(
        upstream_settings, lambda _: httpx2.Response(201, content=body), "/orders", method="POST"
    )

    assert response is not None
    assert response.status_code == 201
    assert credits_of("create_document_order") == before


async def test_a_request_is_counted_and_timed_under_the_old_metric_names(
    upstream_settings: UpstreamSettings,
) -> None:
    before = requests_total("GET", LITE, "200")
    count = "kyckr_api_request_duration_ms_count"

    await get(upstream_settings, answering(200), "/companies/GB%7C12345678/lite")

    assert requests_total("GET", LITE, "200") == before + 1
    assert sample(count, {"method": "GET", "path": LITE}) >= 1


async def test_a_query_string_does_not_change_the_path_label(
    upstream_settings: UpstreamSettings,
) -> None:
    before = requests_total("GET", "/companies", "200")

    await get(upstream_settings, answering(200), "/companies?name=Acme")

    assert requests_total("GET", "/companies", "200") == before + 1


async def test_the_duration_is_recorded_in_milliseconds(
    upstream_settings: UpstreamSettings,
) -> None:
    def slow(_: httpx2.Request) -> httpx2.Response:
        time.sleep(0.15)
        return httpx2.Response(200, json={})

    labels = {"method": "GET", "path": "/companies/:kyckrId/documents"}
    name = "kyckr_api_request_duration_ms"
    total_before = sample(f"{name}_sum", labels)
    in_100_before = sample(f"{name}_bucket", {**labels, "le": "100.0"})
    in_1000_before = sample(f"{name}_bucket", {**labels, "le": "1000.0"})

    await get(upstream_settings, slow, "/companies/GB%7C1/documents")

    assert 150 <= sample(f"{name}_sum", labels) - total_before < 1000
    assert sample(f"{name}_bucket", {**labels, "le": "100.0"}) == in_100_before
    assert sample(f"{name}_bucket", {**labels, "le": "1000.0"}) == in_1000_before + 1
    assert REGISTRY.get_sample_value(f"{name}_bucket", {**labels, "le": "120000.0"}) is not None


async def test_a_request_without_an_answer_counts_with_status_zero(
    upstream_settings: UpstreamSettings,
) -> None:
    before = requests_total("GET", "/companies", "0")

    await get(upstream_settings, time_out, "/companies")

    assert requests_total("GET", "/companies", "0") == before + 1


async def test_a_retried_request_counts_once_per_attempt(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({}, status=429)
    before = requests_total("GET", "/companies", "429")

    await call_tool("search_companies", {"name": "Acme"})

    assert requests_total("GET", "/companies", "429") == before + 3
    assert len(kyckr.requests) == 3


async def test_each_attempt_after_the_first_counts_as_a_retry(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    answers = iter([httpx2.Response(429), httpx2.Response(200, json={"data": []})])
    kyckr.handler = lambda _: next(answers)
    before = retries_total("GET", "/companies")

    await call_tool("search_companies", {"name": "Acme"})

    assert retries_total("GET", "/companies") == before + 1


async def test_a_call_answered_at_the_first_attempt_counts_no_retry(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({"data": []})
    before = retries_total("GET", "/companies")

    await call_tool("search_companies", {"name": "Acme"})

    assert retries_total("GET", "/companies") == before


async def test_a_rate_limit_that_outlasts_the_retries_counts_every_attempt_after_the_first(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    kyckr.answers({}, status=429)
    before = retries_total("GET", "/companies")

    await call_tool("search_companies", {"name": "Acme"})

    assert retries_total("GET", "/companies") == before + 2


async def test_two_separate_calls_to_one_route_count_no_retry(
    upstream_settings: UpstreamSettings,
) -> None:
    before = retries_total("GET", "/companies")

    async with upstream_http(upstream_settings, httpx2.MockTransport(answering(200))) as client:
        await client.get("/companies")
        await client.get("/companies")

    assert retries_total("GET", "/companies") == before


async def test_a_paid_call_retried_after_a_429_counts_each_attempt_and_its_credits_once(
    call_tool: CallTool, kyckr: FakeKyckr
) -> None:
    answers = iter(
        [
            httpx2.Response(429),
            httpx2.Response(200, json={"data": {"companyName": "Acme"}, "cost": {"value": 4}}),
        ]
    )
    kyckr.handler = lambda _: next(answers)
    credits_before = credits_of("get_lite_profile")
    throttled_before = requests_total("GET", LITE, "429")
    answered_before = requests_total("GET", LITE, "200")

    await call_tool("get_lite_profile", {"kyckr_id": "GB|abc"})

    assert requests_total("GET", LITE, "429") == throttled_before + 1
    assert requests_total("GET", LITE, "200") == answered_before + 1
    assert credits_of("get_lite_profile") == credits_before + 4


@pytest.mark.parametrize(
    ("call", "tool"),
    [
        (("GET", "/companies/GB%7C12345678/lite"), "get_lite_profile"),
        (("GET", "/companies/RO%7CJ40%2F8%2F1993/lite"), "get_lite_profile"),
        (("GET", "/companies/GB%7C12345678/enhanced"), "get_enhanced_profile"),
        (("POST", "/orders"), "create_document_order"),
        (("GET", "/orders/9876"), "get_order"),
    ],
)
async def test_a_paid_call_adds_its_cost_to_the_credits_of_its_tool(
    upstream_settings: UpstreamSettings, call: tuple[str, str], tool: str
) -> None:
    method, url = call
    before = credits_of(tool)

    await get(upstream_settings, answering(200, {"cost": {"value": 4}}), url, method=method)

    assert credits_of(tool) == before + 4


@pytest.mark.parametrize(
    ("call", "tool"),
    [
        (("GET", "/companies/GB%7C12345678/enhanced"), "get_enhanced_profile"),
        (("POST", "/orders"), "create_document_order"),
    ],
)
async def test_a_pending_answer_adds_its_cost(
    upstream_settings: UpstreamSettings, call: tuple[str, str], tool: str
) -> None:
    method, url = call
    body = {"data": {"status": "Pending"}, "cost": {"value": 1}}
    before = credits_of(tool)

    await get(upstream_settings, answering(202, body), url, method=method)

    assert credits_of(tool) == before + 1


async def test_polling_an_order_does_not_count_the_cost_of_the_order_again(
    upstream_settings: UpstreamSettings,
) -> None:
    body = {"data": {"status": "Pending", "cost": {"value": 4}}}
    before = credits_of("get_order")

    await get(upstream_settings, answering(200, body), "/orders/9876")

    assert credits_of("get_order") == before


async def test_an_order_answer_without_a_cost_adds_no_credits(
    upstream_settings: UpstreamSettings,
) -> None:
    before = credits_of("get_order")

    await get(upstream_settings, answering(200, {"data": {"status": "Success"}}), "/orders/9876")

    assert credits_of("get_order") == before


async def test_a_free_call_adds_no_credits(upstream_settings: UpstreamSettings) -> None:
    before = all_credits()

    await get(upstream_settings, answering(200, {"cost": {"value": 4}}), "/companies")

    assert all_credits() == before


async def test_a_failed_paid_call_adds_no_credits(upstream_settings: UpstreamSettings) -> None:
    before = credits_of("get_lite_profile")

    await get(upstream_settings, answering(404, {"cost": {"value": 4}}), "/companies/GB%7C1/lite")

    assert credits_of("get_lite_profile") == before


async def test_each_call_makes_a_client_span_named_after_the_route(
    upstream_settings: UpstreamSettings, spans: InMemorySpanExporter
) -> None:
    await get(upstream_settings, answering(200), "/companies/GB%7C12345678/lite")

    (span,) = spans.get_finished_spans()
    assert span.kind is SpanKind.CLIENT
    assert span.name == f"GET {LITE}"
    assert span.attributes == {
        "http.request.method": "GET",
        "url.template": LITE,
        "http.response.status_code": 200,
    }


async def test_a_call_answered_with_an_error_marks_its_span_failed(
    upstream_settings: UpstreamSettings, spans: InMemorySpanExporter
) -> None:
    await get(upstream_settings, answering(404), "/companies/GB%7C12345678/lite")

    (span,) = spans.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR


async def test_a_call_that_raises_marks_its_span_failed_without_the_error(
    upstream_settings: UpstreamSettings, spans: InMemorySpanExporter
) -> None:
    with pytest.raises(RuntimeError):
        await get(upstream_settings, explode, "/companies/GB%7C12345678/lite")

    (span,) = spans.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description is None
    assert span.events == ()


@pytest.mark.parametrize("status", [400, 404, 500])
async def test_a_call_answered_with_an_error_logs_a_warning_with_its_route_and_status(
    status: int, upstream_settings: UpstreamSettings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, UPSTREAM_LOGGER)

    await get(upstream_settings, answering(status), "/companies/GB%7C12345678/lite")

    (record,) = upstream_records(caplog)
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "Kyckr answered with an error"
    assert (record.__dict__["method"], record.__dict__["path"]) == ("GET", LITE)
    assert record.__dict__["status"] == status


async def test_a_call_without_an_answer_logs_a_warning_with_its_traceback_and_status_zero(
    upstream_settings: UpstreamSettings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, UPSTREAM_LOGGER)

    await get(upstream_settings, time_out, "/companies/GB%7C12345678/lite")

    (record,) = upstream_records(caplog)
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "Kyckr request failed"
    assert record.exc_info is not None
    assert record.__dict__["status"] == 0


@pytest.mark.parametrize("status", [200, 202, 302])
async def test_a_call_answered_below_400_logs_nothing(
    upstream_settings: UpstreamSettings, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    caplog.set_level(logging.DEBUG, UPSTREAM_LOGGER)

    await get(upstream_settings, answering(status), "/companies/GB%7C12345678/lite")

    assert upstream_records(caplog) == []


@pytest.mark.parametrize("handler", [answering(500), time_out, explode])
async def test_the_key_and_the_ids_are_in_no_label_or_span(
    upstream_settings: UpstreamSettings, spans: InMemorySpanExporter, handler: Handler
) -> None:
    with contextlib.suppress(RuntimeError):
        await get(upstream_settings, handler, "/companies/RO%7CJ40%2F8%2F12345678/lite")

    recorded = [
        *kyckr_label_values(),
        *(str((s.attributes, s.events, s.status.description)) for s in spans.get_finished_spans()),
    ]
    assert recorded
    assert not any(secret in text for text in recorded for secret in SECRETS)


async def test_the_key_and_the_ids_are_in_no_retry_label(
    upstream_settings: UpstreamSettings,
) -> None:
    async with upstream_http(upstream_settings, httpx2.MockTransport(answering(429))) as client:
        request = client.build_request("GET", "/companies/RO%7CJ40%2F8%2F12345678/lite")
        await client.send(request)
        await client.send(request)

    labels = kyckr_label_values("kyckr_api_retries")
    assert LITE in labels
    assert not any(secret in text for text in labels for secret in SECRETS)


async def test_the_key_and_the_ids_are_in_no_log_line(
    upstream_settings: UpstreamSettings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, UPSTREAM_LOGGER)

    await get(upstream_settings, answering(500), "/companies/RO%7CJ40%2F8%2F12345678/lite")
    await get(upstream_settings, time_out, "/companies/RO%7CJ40%2F8%2F12345678/lite")

    records = upstream_records(caplog)
    assert len(records) == 2
    logged = [record.getMessage() + str(record.__dict__) for record in records]
    assert not any(secret in text for text in logged for secret in SECRETS)


async def test_a_failed_tool_call_logs_neither_the_key_nor_the_ids(
    call_tool: CallTool, kyckr: FakeKyckr, caplog: pytest.LogCaptureFixture
) -> None:
    kyckr.answers({"data": {"detail": "boom"}}, status=500)
    caplog.set_level(logging.DEBUG)
    # As init_telemetry sets it: httpx2 logs every URL at INFO.
    caplog.set_level(logging.WARNING, "httpx2")

    result = await call_tool("get_lite_profile", {"kyckr_id": "RO|J40/8/12345678"})

    assert result.is_error
    formatter = logging.Formatter()
    logged = [formatter.format(record) + str(record.__dict__) for record in caplog.records]
    assert any("Tool call failed" in text for text in logged)
    assert not any(secret in text for text in logged for secret in SECRETS)
