"""The `attach_file` size cap, derived from the MCP transport's request-body limit.

At the feature root rather than in `commands/` because both the input model (which
publishes the number in `content`'s description) and the encoder (which enforces it) need
it, and `commands/` already imports the input model.

The number is not ours to choose. An `attach_file` call arrives as one JSON-RPC body, and
the MCP SDK caps that body at `DEFAULT_MAX_REQUEST_BODY_SIZE` (4 MiB) inside
`StreamableHTTPSessionManager`; FastMCP's subclass neither accepts nor forwards a
`max_request_body_size`, so there is no knob and no outer middleware can widen it.
`content` is standard base64, costing 4 bytes of body per 3 bytes of file, and the rest of
the JSON-RPC envelope gets a fixed allowance. Raising the real ceiling needs a
`max_request_body_size` passthrough on FastMCP's `http_app`, not a bigger number here —
`tests/features/activity_writes/test_attach_file_max_bytes.py` fails if that changes.
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
