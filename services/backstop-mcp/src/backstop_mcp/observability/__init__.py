"""Logging and tracing helpers shared by the Backstop client, features, and the server.

What a log line or span may carry is fixed in `docs/technical/architecture.md` under
Observability. Call sites log with `logging` and name each field themselves
(`extra={"entity_id": party.id, "returned": len(rows)}`); `install_log_handlers` puts every line on
the active span too. Nothing here accepts a whole object and decides which parts are safe.
"""

from backstop_mcp.observability.failures import DeclaresFailureLevel, failure_level
from backstop_mcp.observability.fields import span_attributes
from backstop_mcp.observability.log_handlers import install_log_handlers
from backstop_mcp.observability.operation import OperationOutcome, operation
from backstop_mcp.observability.tool_call import add_call_fields, tool_call_scope

__all__ = [
    "DeclaresFailureLevel",
    "OperationOutcome",
    "add_call_fields",
    "failure_level",
    "install_log_handlers",
    "operation",
    "span_attributes",
    "tool_call_scope",
]
