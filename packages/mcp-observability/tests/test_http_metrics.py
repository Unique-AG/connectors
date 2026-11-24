import logging
from typing import cast
from typing import override

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import BaseRoute
from starlette.routing import Host
from starlette.routing import Match
from starlette.routing import Mount
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.types import Message
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from mcp_observability.metrics import REGISTRY
from mcp_observability.metrics import HttpMetricsMiddleware

type Series = list[dict[str, str]]

REQUESTS = "python_http_requests_total"
DURATIONS = "python_http_request_duration_seconds_count"


def series(sample_name: str) -> Series:
    return [
        dict(sample.labels)
        for family in REGISTRY.collect()
        for sample in family.samples
        if sample.name == sample_name
    ]


def paths(sample_name: str) -> set[str]:
    return {labels["path"] for labels in series(sample_name)}


def total(sample_name: str, **labels: str) -> float:
    return sum(
        sample.value
        for family in REGISTRY.collect()
        for sample in family.samples
        if sample.name == sample_name
        and all(sample.labels.get(key) == value for key, value in labels.items())
    )


def in_flight() -> float:
    return total("python_http_requests_in_progress")


async def ok(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


async def crash(_request: Request) -> PlainTextResponse:
    raise RuntimeError("bug")


async def opaque_app(scope: Scope, receive: Receive, send: Send) -> None:
    await PlainTextResponse("ok")(scope, receive, send)


class CustomRoute(BaseRoute):
    """A route class that has no `path_format`."""

    @override
    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        return (Match.FULL, {}) if scope["path"] == "/custom" else (Match.NONE, {})

    @override
    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        await PlainTextResponse("ok")(scope, receive, send)


@pytest.fixture
def client() -> TestClient:
    inner = Starlette(routes=[Route("/lines/{line_id}", ok)])
    app = Starlette(
        routes=[
            Route("/orders/{order_id:int}", ok),
            Route("/invoices/{invoice_id}", ok, methods=["POST"]),
            Route("/probe", ok),
            Route("/crash/{crash_id}", crash),
            Mount("/shop", app=inner),
            Host("{tenant}.example.com", app=opaque_app),
            CustomRoute(),
        ],
        middleware=[Middleware(HttpMetricsMiddleware, excluded_paths=frozenset({"/probe"}))],
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("sample_name", [REQUESTS, DURATIONS])
def test_unmatched_paths_share_one_series(client: TestClient, sample_name: str) -> None:
    before = total(sample_name, path="unmatched")

    for number in range(100):
        client.get(f"/scanner-{number}/wp-login.php")

    assert not [labels for labels in series(sample_name) if "scanner" in labels["path"]]
    assert total(sample_name, path="unmatched") - before == 100


@pytest.mark.parametrize("sample_name", [REQUESTS, DURATIONS])
def test_a_matched_route_is_labelled_with_its_template(
    client: TestClient, sample_name: str
) -> None:
    client.get("/orders/7")
    client.get("/orders/8")

    assert "/orders/{order_id}" in paths(sample_name)
    assert "/orders/7" not in paths(sample_name)


def test_a_wrong_method_on_a_known_route_keeps_the_template_and_the_405(
    client: TestClient,
) -> None:
    client.get("/invoices/5")

    assert {"method": "GET", "path": "/invoices/{invoice_id}", "status_code": "405"} in series(
        REQUESTS
    )


def test_a_failing_handler_still_has_its_template_and_the_500(client: TestClient) -> None:
    client.get("/crash/9")

    assert {"method": "GET", "path": "/crash/{crash_id}", "status_code": "500"} in series(REQUESTS)


@pytest.mark.parametrize("path", ["/shop/lines/3", "/shop/nope/1"])
def test_a_request_below_a_mount_is_labelled_with_the_mount_template(
    client: TestClient, path: str
) -> None:
    before = total(REQUESTS, path="/shop/{path}")

    client.get(path)

    assert total(REQUESTS, path="/shop/{path}") - before == 1
    assert path not in paths(REQUESTS)


def test_an_app_mounted_twice_is_labelled_with_the_mount_the_request_took() -> None:
    shared = Starlette(routes=[Route("/lines/{line_id}", ok)])
    app = Starlette(
        routes=[Mount("/v1", app=shared), Mount("/v2", app=shared)],
        middleware=[Middleware(HttpMetricsMiddleware, excluded_paths=frozenset())],
    )
    client = TestClient(app)
    v1_before = total(REQUESTS, path="/v1/{path}")
    v2_before = total(REQUESTS, path="/v2/{path}")

    client.get("/v1/lines/3")
    client.get("/v2/lines/3")
    client.get("/v2/lines/4")

    assert total(REQUESTS, path="/v1/{path}") - v1_before == 1
    assert total(REQUESTS, path="/v2/{path}") - v2_before == 2


def test_a_path_that_breaks_route_matching_still_counts_as_unmatched(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    before = total(REQUESTS, path="unmatched", status_code="500")

    with caplog.at_level(logging.WARNING, logger="mcp_observability"):
        client.get("/orders/" + "9" * 4301)

    assert total(REQUESTS, path="unmatched", status_code="500") - before == 1
    lookup_failures = [r for r in caplog.records if r.getMessage().startswith("HTTP metric route")]
    assert len(lookup_failures) == 1
    assert "999" not in lookup_failures[0].getMessage()


def test_an_instrumented_app_mounted_in_another_is_labelled_by_its_own_routes() -> None:
    inner = Starlette(
        routes=[Route("/gadgets/{gadget_id:int}", ok)],
        middleware=[Middleware(HttpMetricsMiddleware, excluded_paths=frozenset())],
    )
    outer = Starlette(routes=[Mount("/api", app=inner)])

    TestClient(outer).get("/api/gadgets/7")

    assert "/gadgets/{gadget_id}" in paths(REQUESTS)


def test_a_request_settles_the_in_flight_gauge(client: TestClient) -> None:
    before = in_flight()

    client.get("/orders/7")

    assert in_flight() == before


@pytest.mark.parametrize(
    ("path", "headers"),
    [("/lines/3", {"host": "acme.example.com"}), ("/custom", {})],
    ids=["host route", "route without path_format"],
)
def test_a_route_without_a_template_is_counted_as_unmatched(
    client: TestClient, path: str, headers: dict[str, str]
) -> None:
    requests_before = total(REQUESTS, path="unmatched")
    in_flight_before = in_flight()

    client.get(path, headers=headers)

    assert total(REQUESTS, path="unmatched") - requests_before == 1
    assert in_flight() == in_flight_before


@pytest.mark.parametrize("sample_name", [REQUESTS, DURATIONS])
def test_excluded_paths_are_not_recorded(client: TestClient, sample_name: str) -> None:
    client.get("/probe")

    assert "/probe" not in paths(sample_name)


async def test_a_non_http_scope_passes_through_unrecorded() -> None:
    received: list[str] = []

    async def app(scope: Scope, _receive: Receive, _send: Send) -> None:
        received.append(cast(str, scope["type"]))

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(_message: Message) -> None:
        pass

    recorded = series(REQUESTS)

    await HttpMetricsMiddleware(app, excluded_paths=frozenset())(
        {"type": "lifespan"}, receive, send
    )

    assert received == ["lifespan"]
    assert series(REQUESTS) == recorded
