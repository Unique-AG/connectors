"""The `attach_file` cap is derived from the MCP transport limit, not chosen.

These are the tests that fail if someone raises the cap without raising the thing that
actually constrains it. `attach_file` bodies arrive as one JSON-RPC request, and the MCP
SDK caps that body inside `StreamableHTTPSessionManager` at
`DEFAULT_MAX_REQUEST_BODY_SIZE`; FastMCP's subclass neither accepts nor forwards a
`max_request_body_size`, so there is no knob. A bigger `ATTACH_FILE_MAX_BYTES` would
publish a ceiling the transport rejects with a bare 413 and no explanation.
"""

from fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE
from starlette.testclient import TestClient

from backstop_mcp.features.activity_writes import (
    ATTACH_FILE_MAX_BYTES,
    attach_file_max_bytes_message,
)


def test_a_file_at_the_cap_still_fits_in_one_request_body() -> None:
    """`content` is standard base64: 4 bytes of body per 3 bytes of file, plus the envelope."""
    encoded_size = -(-ATTACH_FILE_MAX_BYTES // 3) * 4

    assert encoded_size < DEFAULT_MAX_REQUEST_BODY_SIZE


def test_the_published_ceiling_never_overstates_the_cap() -> None:
    """Rounded down, so an agent that believes the number does not hit a rejection."""
    published_mb = float(attach_file_max_bytes_message().removesuffix(" MB"))

    assert published_mb * 1024 * 1024 <= ATTACH_FILE_MAX_BYTES


def test_fastmcp_still_pins_the_sdk_body_limit() -> None:
    """The reason the cap is derived. If FastMCP gains a knob, this test says so."""
    mcp = FastMCP("body-limit-probe")
    app = mcp.http_app()

    with TestClient(app):
        managers = [
            manager
            for route in app.routes
            if isinstance(
                manager := getattr(getattr(route, "app", None), "session_manager", None),
                StreamableHTTPSessionManager,
            )
        ]

    assert managers, "no streamable-HTTP session manager found on the FastMCP app"
    for manager in managers:
        assert manager.max_request_body_size == DEFAULT_MAX_REQUEST_BODY_SIZE
