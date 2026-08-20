"""Every Graph failure a caller has to answer differently, from the status that produces it.

The bodies are synthesised copies of the shapes Graph documents, not captures from a tenant.
"""

from asyncio import CancelledError
from collections.abc import Callable

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphThrottled,
    GraphUnavailable,
    graph_errors,
)

from .conftest import GRAPH_V1, RecordedSleeps

REQUEST_ID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"

type _Respond = Callable[[httpx.Request], httpx.Response]


def error_body(code: str, message: str) -> dict[str, object]:
    return {"error": {"code": code, "message": message, "innerError": {"code": code}}}


def always(status: int, headers: dict[str, str], body: dict[str, object]) -> _Respond:
    """The same failure to every attempt, as a fresh response each time.

    The retry handler closes each response it discards, so a single `httpx.Response` reused
    across attempts would be read after closing.
    """

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
        # No remedy of its own: a rejected `$filter` is neither retriable nor a permission
        # problem, so it stays the base failure rather than getting a category invented for it.
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
    """The one place a status alone is not enough to sort a failure by remedy.

    Graph rate limits with a 503 as well as with a 429, and the only thing that says which it did is
    `Retry-After`: a service naming the second it will answer again is holding a caller off, not
    falling over. The remedies are opposite — wait exactly that long and then look at quota, versus
    retry once and then report an outage — so a 503 with the header has to land on the throttling
    side of that split and a 503 without it on the outage side. The SDK's own retry handler reads
    the header on a 503 the same way, which is what makes the `retried` label on
    `graph_throttled_total` true of the result.

    A 500 is here as the control: it is not a status the SDK retries at all, so nothing about it
    changes.
    """
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
    """Throttling only reaches a caller once the SDK has waited `Retry-After` out three times.

    Which is the whole reason `retry_after_seconds` is on the error: by the time a tool sees
    this, "try again in a moment" is already known to be wrong.
    """
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
    """Two Teams transcript refusals share a status and an outer code and have opposite remedies —
    one is a tenant switch only a Teams administrator can flip, the other is a format to ask for
    again — so `innerError.code` is the whole of the difference. It is not one of the SDK's typed
    inner-error fields, so it arrives in `additional_data` and would be dropped without this.
    """
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
    """A connection failure never becomes an `APIError` — there is no response to build one from."""
    graph.get("/me").mock(side_effect=httpx.ConnectError("name resolution failed"))

    with pytest.raises(GraphUnavailable) as raised, graph_errors("a_test"):
        _ = await client.me.get()

    assert raised.value.status is None
    assert "name resolution failed" in str(raised.value)


async def test_a_redirect_the_sdk_gave_up_on_is_worded_rather_than_escaping_unworded(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    """The SDK raises its own exceptions that are not `APIError`, and they used to escape.

    `kiota_http` has a family for the failures that happen outside the request/response cycle
    `_classify` describes — too many redirects, a response it could not read, a body it could not
    deserialize. None carries a status, a code or a request id, so none can be classified from a
    response; without a clause for them a caller got an unworded `ToolError` and the call was
    counted under the `error` sentinel that means "an exception this seam cannot describe".
    """
    graph.get("/me").mock(return_value=httpx.Response(302, headers={"location": f"{GRAPH_V1}/me"}))

    with pytest.raises(GraphUnavailable) as raised, graph_errors("a_test"):
        _ = await client.me.get()

    assert raised.value.status is None
    assert "could not read" in str(raised.value)


def test_a_cancelled_call_stays_cancelled_and_is_not_reported_as_a_graph_failure() -> None:
    """The caller went away; Graph did nothing wrong.

    Re-raised untranslated, because the task group that cancelled this has to learn it was obeyed —
    a `CancelledError` swallowed into a `GraphUnavailable` is a task that reports success to a
    cancellation. It also stops being counted as a Graph failure, which is what an MCP client
    hanging up used to look like on a dashboard.

    Raised in the block rather than off the wire: `CancelledError` is a `BaseException`, and respx
    will only stand in for an `Exception`.
    """
    with pytest.raises(CancelledError), graph_errors("a_test"):
        raise CancelledError("the client hung up")
