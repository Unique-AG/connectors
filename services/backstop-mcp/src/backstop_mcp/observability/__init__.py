"""Logging and tracing helpers shared by the Backstop client, features, and the server. How to
use them: `docs/technical/architecture.md`, Observability."""

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
