from asyncio import CancelledError
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import override

import fastmcp
from fastmcp.exceptions import ToolError
from fastmcp.exceptions import ValidationError as ArgumentsRejected
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import InputRequiredToolResult, ToolResult
from mcp.types import CallToolRequestParams
from opentelemetry import metrics
from pydantic import ValidationError

from office_365_mcp.cardinality import UNRESOLVED_NAME
from office_365_mcp.graph_client import GraphFailure, measured_graph_operation
from office_365_mcp.shared.seam import TokenExchangeFailed

__all__ = [
    "TOOL_OUTCOMES",
    "TOOL_OUTCOMES_TOTAL",
    "TOOL_REFUSALS",
    "GraphOperationMiddleware",
    "start_tool_outcomes",
]

TOOL_REFUSALS: tuple[type[Exception], ...] = (ToolError, ValidationError, ArgumentsRejected)

TOOL_OUTCOMES_TOTAL = "tool_outcomes_total"
TOOL_OUTCOMES: tuple[str, ...] = (
    "ok",
    "asked",
    "refused",
    "graph",
    "token",
    "error",
    "cancelled",
)

_outcomes = metrics.get_meter("office_365_mcp").create_counter(
    TOOL_OUTCOMES_TOTAL,
    description=(
        "MCP tool calls by how they ended. `asked` returned a question for a person to confirm. "
        "`refused` is a refusal the tool raised on purpose, such as a malformed handle. `graph` "
        "is a refusal or failure with a Graph failure in its cause chain. `token` is a call that "
        "got no Graph token. `error` is any other exception, or a result that the tool returned "
        "as an error. "
        "`cancelled` is a call that the client or the server cancelled."
    ),
)

_FASTMCP_PACKAGE = Path(fastmcp.__file__).parent


def start_tool_outcomes(operations: Iterable[str]) -> None:
    for operation in operations:
        for outcome in TOOL_OUTCOMES:
            _outcomes.add(0, {"operation": operation, "outcome": outcome})


def _causes(error: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__


def _context_and_causes(error: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    waiting: list[BaseException] = [error]
    while waiting:
        current = waiting.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        waiting.extend(
            link for link in (current.__cause__, current.__context__) if link is not None
        )


def _raised_by_fastmcp(error: BaseException) -> bool:
    trace = error.__traceback__
    if trace is None:
        return False
    while trace.tb_next is not None:
        trace = trace.tb_next
    return Path(trace.tb_frame.f_code.co_filename).is_relative_to(_FASTMCP_PACKAGE)


def _ending(error: Exception) -> BaseException:
    if isinstance(error, ToolError) and _raised_by_fastmcp(error) and error.__cause__ is not None:
        return error.__cause__
    return error


def _outcome(error: Exception) -> str:
    ending = _ending(error)
    if any(isinstance(cause, TokenExchangeFailed) for cause in _causes(ending)):
        return "token"
    if any(isinstance(cause, GraphFailure) for cause in _causes(ending)):
        return "graph"
    if isinstance(ending, ArgumentsRejected):
        return "refused"
    if isinstance(ending, ToolError) and not _raised_by_fastmcp(ending):
        graph_behind = any(isinstance(cause, GraphFailure) for cause in _context_and_causes(ending))
        return "graph" if graph_behind else "refused"
    return "error"


class GraphOperationMiddleware(Middleware):
    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        if name == UNRESOLVED_NAME:
            return await call_next(context)
        try:
            with measured_graph_operation(name, not_failures=TOOL_REFUSALS):
                result = await call_next(context)
        except CancelledError:
            _outcomes.add(1, {"operation": name, "outcome": "cancelled"})
            raise
        except Exception as error:
            _outcomes.add(1, {"operation": name, "outcome": _outcome(error)})
            raise
        if isinstance(result, InputRequiredToolResult):
            outcome = "asked"
        elif result.is_error:
            outcome = "error"
        else:
            outcome = "ok"
        _outcomes.add(1, {"operation": name, "outcome": outcome})
        return result
