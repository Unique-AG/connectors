"""Every Graph failure a caller has to answer differently, from the status that produces it.

The bodies are synthesised copies of the shapes Graph documents, not captures from a tenant.
"""

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

from .conftest import RecordedSleeps

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

    with pytest.raises(expected) as raised, graph_errors():
        _ = await client.me.get()

    assert type(raised.value) is expected
    assert raised.value.status == status
    assert raised.value.code == code
    assert raised.value.request_id == REQUEST_ID


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

    with pytest.raises(GraphThrottled) as raised, graph_errors():
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

    with pytest.raises(GraphThrottled) as raised, graph_errors():
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

    with pytest.raises(GraphForbidden) as raised, graph_errors():
        _ = await client.me.get()

    assert raised.value.code == "Forbidden", "the outer code says nothing actionable"
    assert raised.value.inner_code == "GraphAccessToTranscriptsDisabled"


async def test_an_error_without_an_inner_code_reports_none_rather_than_the_outer_one(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    graph.get("/me").mock(
        return_value=httpx.Response(403, json={"error": {"code": "accessDenied", "message": "no"}})
    )

    with pytest.raises(GraphForbidden) as raised, graph_errors():
        _ = await client.me.get()

    assert raised.value.inner_code is None


async def test_never_reaching_graph_is_reported_as_upstream_not_as_a_bad_request(
    client: GraphServiceClient, graph: respx.MockRouter
) -> None:
    """A connection failure never becomes an `APIError` — there is no response to build one from."""
    graph.get("/me").mock(side_effect=httpx.ConnectError("name resolution failed"))

    with pytest.raises(GraphUnavailable) as raised, graph_errors():
        _ = await client.me.get()

    assert raised.value.status is None
    assert "name resolution failed" in str(raised.value)
