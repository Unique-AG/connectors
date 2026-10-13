import functools
import inspect
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool, ToolResult
from fastmcp.tools.tool_transform import ArgTransform, TransformedTool, forward_raw
from pydantic import BaseModel, ValidationError

from tiingo_mcp.openapi.routes import MCP_NAMES


def payload_rows(result: ToolResult) -> list[dict[str, Any]]:
    """The list a tool returned: FastMCP wraps it as `{"result": [...]}`."""
    content = result.structured_content
    assert content is not None and "result" in content, "tool returned no list payload"
    return content["result"]


async def forward_rows(**arguments: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    """Call the generated tool from inside a wrapper and return its list payload."""
    return payload_rows(await forward_raw(**arguments))


async def require_tool(mcp: FastMCP, name: str) -> Tool:
    """Look up a registered tool, so a composite fails at startup if its dependency is missing."""
    tool = await mcp.get_tool(name)
    assert tool is not None, f"tool {name} is not registered yet: register it before its callers"
    return tool


async def run_rows[Row: BaseModel](
    tool: Tool,
    arguments: dict[str, Any],
    row: type[Row],
) -> list[Row]:
    """Run a list-returning tool and parse each item as `row`."""
    return [row.model_validate(item) for item in payload_rows(await tool.run(arguments))]


def readable_validation_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Report validation failures as a tool error naming the field, not a bare -32602."""

    @functools.wraps(fn)
    async def checked(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        try:
            return await fn(*args, **kwargs)
        except ValidationError as exc:
            kind = "Invalid arguments" if exc.title == fn.__name__ else "Unexpected Tiingo response"
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
            )
            raise ToolError(f"{kind}: {problems}") from exc

    return checked


async def wrap_tool(mcp: FastMCP, operation_id: str, fn: Callable[..., Any]) -> None:
    """Replace the generated tool for `operation_id` with `fn`, named and described by `fn`.

    Only the arguments `fn` declares stay visible. `fn` calls the generated tool via `forward_rows`.
    """
    generated_name = MCP_NAMES[operation_id]
    generated = await mcp.get_tool(generated_name)
    assert generated is not None, f"no generated tool {generated_name}"
    doc = inspect.getdoc(fn)
    assert doc, f"{fn.__name__} needs a docstring: it is the tool description"
    hidden = generated.parameters["properties"].keys() - inspect.signature(fn).parameters
    mcp.disable(names={generated_name}, components={"tool"})
    mcp.add_tool(
        TransformedTool.from_tool(
            generated,
            name=fn.__name__,
            description=" ".join(doc.split()),
            transform_fn=readable_validation_errors(fn),
            transform_args={arg: ArgTransform(hide=True) for arg in hidden},
        )
    )
