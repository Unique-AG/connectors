"""The one process-wide service holder.

`create_app()` is the composition root: it builds every config and every long-lived
collaborator, wraps them in `Services`, and calls `configure_services` once. Tool functions
can't take constructor arguments (FastMCP calls them with a plain signature), so they reach
their collaborators through `get_services()`.

One holder rather than one global per subsystem, so there is one place to configure and one
place to reset.
"""

from dataclasses import dataclass

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory


@dataclass(frozen=True)
class Services:
    """Everything a tool or middleware may need, resolved once at startup."""

    backstop: BackstopClientFactory


_services: Services | None = None


def configure_services(services: Services) -> None:
    """Install the process-wide services. Call once, from `create_app()`.

    Asserts rather than overwriting: a second install would silently orphan the first
    `BackstopClientFactory` and leak its connection pool. Call `reset_services()` to replace.
    """
    global _services
    assert _services is None, "configure_services() called twice; reset_services() first"
    _services = services


def get_services() -> Services:
    assert _services is not None, "configure_services() must be called during app startup"
    return _services


async def reset_services() -> None:
    """Drop the installed services, closing anything they own.

    The single teardown hook — used by the test suite's autouse fixture, since each test
    function runs on its own event loop and a connection pool bound to a closed loop would
    fail the next time it was touched.
    """
    global _services
    services = _services
    _services = None
    if services is not None:
        await services.backstop.aclose()


async def get_backstop_client() -> BackstopClient:
    """Build a Backstop API client authenticated as the current MCP caller.

    The entry point tool implementations use. Raises `auth.context.NotConnectedError` if the
    caller hasn't completed the login flow.
    """
    return await get_services().backstop.for_current_caller()
