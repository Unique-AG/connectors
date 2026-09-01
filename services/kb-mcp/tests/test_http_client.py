"""Liveness reporting, and wiring our client into unique_sdk."""

import asyncio

import httpx
import pytest
import unique_sdk
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from kb_mcp import http_client
from kb_mcp.health import PoolHealthMiddleware
from kb_mcp.http_client import (
    PooledHTTPXClient,
    install_pooled_http_client,
    pool_is_exhausted,
)
from kb_mcp.settings import get_settings

pytestmark = pytest.mark.ai


@pytest.fixture(autouse=True)
def _restore_sdk_client():
    """Restore the global SDK client after each test."""
    original_client = unique_sdk.default_http_client
    original_installed = http_client._installed
    yield
    unique_sdk.default_http_client = original_client
    http_client._installed = original_installed


def _app(is_unhealthy) -> TestClient:
    async def ok(_request):
        return JSONResponse({"status": "ok"})

    app = Starlette(
        routes=[Route("/probe", ok), Route("/health", ok), Route("/mcp", ok)],
    )
    return TestClient(PoolHealthMiddleware(app, is_unhealthy=is_unhealthy))


def test_probe_passes_through_while_healthy():
    client = _app(lambda: False)
    assert client.get("/probe").status_code == 200
    assert client.get("/health").status_code == 200


def test_probe_fails_once_the_pool_is_exhausted():
    client = _app(lambda: True)
    response = client.get("/probe")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


def test_trailing_slash_is_still_a_probe():
    assert _app(lambda: True).get("/probe/").status_code == 503


def test_only_probe_paths_are_short_circuited():
    """An exhausted pool must not turn every route into a 503."""
    assert _app(lambda: True).get("/mcp").status_code == 200


def test_health_check_failure_fails_open():
    """A broken check must never be why a healthy pod is restarted."""

    def boom() -> bool:
        raise RuntimeError("counter unavailable")

    assert _app(boom).get("/probe").status_code == 200


def test_pool_exhaustion_latches():
    client = PooledHTTPXClient()
    assert client.pool_exhausted is False
    client._note_pool_exhausted()
    assert client.pool_exhausted is True
    client._note_pool_exhausted()
    assert client.pool_exhausted is True


def test_pool_is_exhausted_is_false_before_install():
    http_client._installed = None
    assert pool_is_exhausted() is False


def test_install_keeps_the_sync_path_on_requests():
    """Keep synchronous SDK requests on RequestsClient."""
    install_pooled_http_client(get_settings())

    installed = unique_sdk.default_http_client
    assert isinstance(installed, unique_sdk.RequestsClient)
    assert isinstance(installed._async_fallback_client, PooledHTTPXClient)


def test_installed_client_bounds_pool_acquisition():
    """A float timeout here would silently restore pool=600 and the stall."""
    install_pooled_http_client(get_settings())
    installed = unique_sdk.default_http_client
    assert installed is not None
    client = installed._async_fallback_client
    assert isinstance(client, PooledHTTPXClient)

    timeout = client._timeout
    assert isinstance(timeout, httpx.Timeout)
    settings = get_settings()
    assert timeout.pool == settings.http_pool_timeout_seconds
    assert timeout.read == 600.0, "request duration must be unchanged"
    limits = client._limits
    assert limits.max_connections == settings.http_max_connections
    assert limits.max_keepalive_connections == settings.http_max_keepalive_connections


@pytest.mark.asyncio
async def test_cancelled_error_propagates_unwrapped():
    """Wrapping CancelledError would let retry_on_error re-run a cancelled request."""
    client = PooledHTTPXClient()

    async def boom(*_args, **_kwargs):
        raise TimeoutError("not a cancel")

    client._client_async.request = boom  # type: ignore[method-assign]
    with pytest.raises(unique_sdk.APIConnectionError):
        await client.request_async("GET", "http://example.invalid/", headers={})

    async def raise_cancel(*_args, **_kwargs):
        raise asyncio.CancelledError()

    client._client_async.request = raise_cancel  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await client.request_async("GET", "http://example.invalid/", headers={})


def test_sync_request_is_refused():
    """Guards against someone assigning this client as the primary."""
    client = PooledHTTPXClient()
    with pytest.raises(NotImplementedError, match="async-only"):
        client.request("GET", "http://example.invalid/", headers={})
