"""`attach_file` size cap: 3/4 of the MCP transport body limit minus envelope room.

Raising it needs a FastMCP `max_request_body_size` passthrough.
"""

from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE

__all__ = ["ATTACH_FILE_MAX_BYTES", "attach_file_max_bytes_message"]

# Room for the JSON-RPC envelope around `content`: method, id, tool name, and the rest of
# the `activity` object. Generous on purpose — being wrong the other way costs the agent a
# transport 413 with no explanation instead of our actionable message.
_ENVELOPE_ALLOWANCE_BYTES = 64 * 1024

ATTACH_FILE_MAX_BYTES = (DEFAULT_MAX_REQUEST_BODY_SIZE - _ENVELOPE_ALLOWANCE_BYTES) * 3 // 4


def attach_file_max_bytes_message() -> str:
    """The cap in megabytes, for a docstring or an error the agent reads.

    Rounded *down* to a tenth so the published number is always reachable — a ceiling that
    is optimistic by a rounding step sends the agent into an avoidable rejection.
    """
    tenths = ATTACH_FILE_MAX_BYTES * 10 // (1024 * 1024)
    return f"{tenths // 10}.{tenths % 10} MB"
