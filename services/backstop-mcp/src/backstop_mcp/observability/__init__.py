"""Logging and tracing helpers shared by the Backstop client, features, and the server. How to
use them: `docs/technical/architecture.md`, Observability."""

from backstop_mcp.observability.events import (
    error_event,
    failure_event,
    info_event,
    warning_event,
)
from backstop_mcp.observability.failures import DeclaresFailureLevel, failure_level, most_severe
from backstop_mcp.observability.fields import failed_fields, span_attributes
from backstop_mcp.observability.operation import OperationOutcome, operation
from backstop_mcp.observability.redaction import install_caller_failure_redaction
from backstop_mcp.observability.tool_call import add_call_fields, tool_call_scope

__all__ = [
    "DeclaresFailureLevel",
    "OperationOutcome",
    "add_call_fields",
    "error_event",
    "failed_fields",
    "failure_event",
    "failure_level",
    "install_caller_failure_redaction",
    "most_severe",
    "operation",
    "span_attributes",
    "tool_call_scope",
]
