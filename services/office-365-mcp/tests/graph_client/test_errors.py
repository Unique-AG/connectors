"""Every Graph failure a caller has to answer differently, from the status that produces it."""

import logging
from asyncio import CancelledError
from collections.abc import Callable

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from office_365_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphThrottled,
    GraphUnavailable,
    graph_errors,
)
from tests.conftest import RecordedSleeps

from .conftest import GRAPH_V1

REQUEST_ID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"

type _Respond = Callable[[httpx.Request], httpx.Response]


def error_body(code: str, message: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message, "innerError": {"code": code}}}


def always(status: int, headers: dict[str, str], body: dict[str, object]) -> _Respond:
    """A fresh response each time: the retry handler closes each response it discards, so one
    reused `httpx.Response` would be read after closing."""

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers=headers, json=body)

    return respond


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "InvalidAuthenticationToken", GraphForbidden),
        (403, "accessDenied", GraphForbidden),
        (404, "itemNotFound", GraphNotFound),
        (500, "internalServerError", GraphUnavailable),
        # No remedy of its own: a rejected `$filter` is neither retriable nor a permission problem.
        (400, "BadRequest", GraphFailure),
    ],
)
async def test_the_status_decides_the_error(
    client: GraphServiceClient,
    graph: respx.MockRouter,
    status: int,
    code: str,
    expected: type[GraphFailure],
) -> None:
    graph.get("/me").mock(
        return_value=httpx.Response(
            status,
            headers={"request-id": REQUEST_ID},
            json=error_body(code, "synthesised failure"),
        )
    )

    with pytest.raises(expected) as raised, graph_errors("a_test"):
        _ = await client.me.get()

    assert type(raised.value) is expected
    assert raised.value.status == status
    assert raised.value.code == code
    assert raised.value.request_id == REQUEST_ID


@pytest.mark.parametrize(
    ("status", "headers", "expected"),
    [
        (429, {"Retry-After": "10"}, GraphThrottled),
        (503, {"Retry-After": "10"}, GraphThrottled),
        (503, {}, GraphUnavailable),
        (504, {}, GraphUnavailable),
        (500, {}, GraphUnavailable),
    ],
    ids=["429-with-delay", "503-with-delay", "503-alone", "504", "500"],
)
@pytest.mark.usefixtures("retry_sleeps")
async def test_a_5xx_is_throttling_when_it_named_a_delay_and_an_outage_when_it_did_not(
    client: GraphServiceClient,
    graph: respx.MockRouter,
    status: int,
    headers: dict[str, str],
    expected: type[GraphFailure],
) -> None:
    """Graph rate limits with a 503 as well as a 429, and only `Retry-After` says which it did.
    The SDK's own retry handler reads the header on a 503 the same way, which is what makes the
    `retried` label on `graph_throttled_total` true of the result. The 500 is the control: not a
    status the SDK retries at all."""
    graph.get("/me").mock(
        side_effect=always(status, headers, error_body("serviceError", "synthesised failure"))
    )

    with pytest.raises(expected) as raised, graph_errors("a_test"):
        _ = await client.me.get()

    assert type(raised.value) is expected
    assert raised.value.status == status
    if isinstance(raised.value, GraphThrottled):
        assert raised.value.retry_after_seconds == 10.0, (
            "the delay is the remedy, so it has to survive the classification"
        )


async def test_a_429_that_outlasts_the_retries_carries_graphs_own_retry_after(
    client: GraphServiceClient,
    graph: respx.MockRouter,
    retry_sleeps: RecordedSleeps,
) -> None:
    """Throttling reaches a caller only after the SDK waited `Retry-After` out three times, which
    is why `retry_after_seconds` is on the error: "in a moment" is already known to be wrong."""
    graph.get("/me").mock(
        side_effect=always(
            429,
            {"Retry-After": "10", "request-id": REQUEST_ID},
            error_body("TooManyRequests", "Please retry again later."),
        )
    )

    with pytest.raises(GraphThrottled) as raised, graph_errors("a_test"):
        _ = await client.me.get()

    assert raised.value.retry_after_seconds == 10.0
    assert raised.value.code == "TooManyRequests"
    assert retry_sleeps.delays == [10, 10, 10]


async def test_a_throttle_without_a_retry_after_says_so_rather_than_guessing(
    client: GraphServiceClient,
    graph: respx.MockRouter,
    retry_sleeps: RecordedSleeps,
) -> None:
    graph.get("/me").mock(
        side_effect=always(429, {}, error_body("TooManyRequests", "Please retry again later."))
    )

    with pytest.raises(GraphThrottled) as raised, graph_errors("a_test"):
        _ = await client.me.get()

    assert raised.value.retry_after_seconds is None
    assert retry_sleeps.delays, "the SDK still backs off, it just picks the delay itself"


async def test_the_inner_code_is_carried_because_it_is_the_only_thing_that_differs(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    """Two Teams transcript refusals share a status and an outer code with opposite remedies, so
    `innerError.code` is the whole difference. It is not one of the SDK's typed inner-error fields,
    so it arrives in `additional_data` and would be dropped without this."""
    graph.get("/me").mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "code": "Forbidden",
                    "message": "Graph API access to transcripts is disabled for this tenant.",
                    "innerError": {"code": "GraphAccessToTranscriptsDisabled"},
                }
            },
        )
    )

    with pytest.raises(GraphForbidden) as raised, graph_errors("a_test"):
        _ = await client.me.get()

    assert raised.value.code == "Forbidden", "the outer code says nothing actionable"
    assert raised.value.inner_code == "GraphAccessToTranscriptsDisabled"


async def test_an_error_without_an_inner_code_reports_none_rather_than_the_outer_one(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    graph.get("/me").mock(
        return_value=httpx.Response(403, json={"error": {"code": "accessDenied", "message": "no"}})
    )

    with pytest.raises(GraphForbidden) as raised, graph_errors("a_test"):
        _ = await client.me.get()

    assert raised.value.inner_code is None


async def test_never_reaching_graph_is_reported_as_upstream_not_as_a_bad_request(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    """A connection failure never becomes an `APIError`: there is no response to build one from."""
    graph.get("/me").mock(side_effect=httpx.ConnectError("name resolution failed"))

    with pytest.raises(GraphUnavailable) as raised, graph_errors("a_test"):
        _ = await client.me.get()

    assert raised.value.status is None
    assert "name resolution failed" in str(raised.value)


async def test_a_redirect_the_sdk_gave_up_on_is_worded_rather_than_escaping_unworded(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    """`kiota_http` has its own family for failures outside the request and response cycle
    `_classify` describes: too many redirects, an unreadable response, an undeserializable body.
    None carries a status, code or request id, so without a clause a caller gets an unworded
    `ToolError` counted under the `error` sentinel."""
    graph.get("/me").mock(return_value=httpx.Response(302, headers={"location": f"{GRAPH_V1}/me"}))

    with pytest.raises(GraphUnavailable) as raised, graph_errors("a_test"):
        _ = await client.me.get()

    assert raised.value.status is None
    assert "could not read" in str(raised.value)


def test_a_cancelled_call_stays_cancelled_and_is_not_reported_as_a_graph_failure() -> None:
    """Re-raised untranslated: the task group that cancelled this has to learn it was obeyed, and a
    `CancelledError` swallowed into a `GraphUnavailable` reports success to a cancellation. Raised
    in the block and not off the wire, because respx stands in only for an `Exception`."""
    with pytest.raises(CancelledError), graph_errors("a_test"):
        raise CancelledError("the client hung up")


async def test_a_body_the_sdk_cannot_read_keeps_the_status_it_arrived_with(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    graph.get("/me").mock(
        return_value=httpx.Response(
            500, text="<html>502 Bad Gateway</html>", headers={"content-type": "text/html"}
        )
    )

    with pytest.raises(GraphUnavailable) as raised, graph_errors("a_test"):
        _ = await client.me.get()

    assert raised.value.status == 500
    assert raised.value.code is None
    assert "Microsoft Graph returned 500" in str(raised.value)


def test_a_bare_exception_is_reported_as_an_answer_that_could_not_be_read() -> None:
    with pytest.raises(GraphUnavailable) as raised, graph_errors("a_test"):
        raise Exception("no parser for this content type")

    assert raised.value.status is None
    assert "could not read" in str(raised.value)


def test_a_bug_of_our_own_is_not_reported_as_graph_being_unavailable() -> None:
    """An `Exception` subclass raised inside the block is this connector's fault; translated to
    `GraphUnavailable` it would tell an operator to retry and blame Microsoft for our defect."""
    for ours in (AssertionError("an invariant of ours"), TypeError("a bug of ours")):
        with pytest.raises(type(ours)), graph_errors("a_test"):
            raise ours


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (400, "Invalid filter clause."),
        (409, "Invalid filter clause."),
        (403, "Invalid filter clause."),
        (404, None),
    ],
)
async def test_graph_failures_keep_graphs_reason_out_of_their_logged_message(
    client: GraphServiceClient, graph: respx.MockRouter, status: int, reason: str | None
) -> None:
    graph.get("/me").mock(
        return_value=httpx.Response(status, json=error_body("aCode", "Invalid filter clause."))
    )

    with pytest.raises(GraphFailure) as raised, graph_errors("a_test"):
        _ = await client.me.get()

    assert raised.value.reason == reason
    assert "Invalid filter clause" not in str(raised.value)


_OR_FILTER = "An internal server error occurred. The operation failed., Unrecognized filter"


class TestAFailedGraphCallLeavesFieldsAnOperatorCanSearch:
    async def test_a_server_error_keeps_the_reason_graph_gave(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me").mock(
            return_value=httpx.Response(
                500,
                headers={"request-id": REQUEST_ID},
                json=error_body("ErrorInternalServerError", _OR_FILTER),
            )
        )

        with pytest.raises(GraphUnavailable) as raised, graph_errors("a_test"):
            _ = await client.me.get()

        assert raised.value.reason == _OR_FILTER

    async def test_the_log_record_and_the_span_carry_the_same_fields(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        graph.get("/me").mock(
            return_value=httpx.Response(
                500,
                headers={"request-id": REQUEST_ID},
                json=error_body("ErrorInternalServerError", _OR_FILTER),
            )
        )
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        with (
            caplog.at_level(logging.INFO, logger="office_365_mcp.graph_client.errors"),
            provider.get_tracer("test").start_as_current_span("tool"),
            pytest.raises(GraphUnavailable),
            graph_errors("a_test", step="a_step"),
        ):
            _ = await client.me.get()

        [record] = [r for r in caplog.records if r.getMessage() == "graph call failed"]
        expected = {
            "graph_operation": "a_test",
            "graph_step": "a_step",
            "graph_remedy": "unavailable",
            "graph_status": 500,
            "graph_code": "ErrorInternalServerError",
            "graph_inner_code": "ErrorInternalServerError",
            "graph_request_id": REQUEST_ID,
            "graph_reason": _OR_FILTER,
        }
        assert record.levelno == logging.WARNING
        assert {name: getattr(record, name) for name in expected} == expected
        [span] = exporter.get_finished_spans()
        assert dict(span.attributes or {}) == expected

    async def test_a_missing_item_is_logged_below_warning(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        graph.get("/me").mock(
            return_value=httpx.Response(404, json=error_body("itemNotFound", "not here"))
        )

        with (
            caplog.at_level(logging.INFO, logger="office_365_mcp.graph_client.errors"),
            pytest.raises(GraphNotFound),
            graph_errors("a_test"),
        ):
            _ = await client.me.get()

        [record] = [r for r in caplog.records if r.getMessage() == "graph call failed"]
        assert record.levelno == logging.INFO

    async def test_an_unreachable_graph_is_logged_without_a_code(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        graph.get("/me").mock(side_effect=httpx.ConnectError("no route"))

        with (
            caplog.at_level(logging.INFO, logger="office_365_mcp.graph_client.errors"),
            pytest.raises(GraphUnavailable),
            graph_errors("a_test"),
        ):
            _ = await client.me.get()

        [record] = [r for r in caplog.records if r.getMessage() == "graph call failed"]
        assert record.__dict__["graph_remedy"] == "unavailable"
        assert "graph_code" not in record.__dict__
