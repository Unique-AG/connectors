"""Logging and tracing helpers shared by the Backstop client, features, and the server.

What a log line or span may carry is fixed in `docs/technical/architecture.md` under
Observability. Call sites name each field themselves (`entity_id=party.id`,
`returned=len(rows)`). Nothing here accepts a whole object and decides which parts are safe.
"""

from backstop_mcp.observability.events import (
    error_event,
    failure_event,
    info_event,
    warning_event,
)
from backstop_mcp.observability.failures import DeclaresFailureLevel, failure_level
from backstop_mcp.observability.fields import span_attributes
from backstop_mcp.observability.operation import OperationOutcome, operation
from backstop_mcp.observability.tool_call import annotate_tool_call, tool_call_scope

__all__ = [
    "DeclaresFailureLevel",
    "OperationOutcome",
    "annotate_tool_call",
    "error_event",
    "failure_event",
    "failure_level",
    "info_event",
    "operation",
    "span_attributes",
    "tool_call_scope",
    "warning_event",
]
