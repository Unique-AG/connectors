"""Fields a tool contributes to its own `tool.call.*` lines and span."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from opentelemetry import trace

from backstop_mcp.observability.fields import span_attributes


class ToolCallFields:
    def __init__(self) -> None:
        self._fields: dict[str, object] = {}

    def add(self, fields: Mapping[str, object]) -> None:
        self._fields.update(fields)

    @property
    def fields(self) -> Mapping[str, object]:
        return dict(self._fields)


# A mutable holder rather than a value: FastMCP may run the tool under a copied context, and a
# copy still points at the same holder, where a `.set()` inside the tool would be lost.
_CURRENT: ContextVar[ToolCallFields | None] = ContextVar("backstop_mcp_tool_call", default=None)


@contextmanager
def tool_call_scope() -> Generator[ToolCallFields]:
    holder = ToolCallFields()
    token = _CURRENT.set(holder)
    try:
        yield holder
    finally:
        _CURRENT.reset(token)


def add_call_fields(**fields: object) -> None:
    """Attach `fields` to the current tool call's span and its completion line.

    No-op outside one.
    """
    trace.get_current_span().set_attributes(span_attributes(fields))
    holder = _CURRENT.get()
    if holder is not None:
        holder.add(fields)
