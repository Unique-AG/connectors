import inspect
from collections.abc import Callable, Mapping
from typing import cast

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool, ToolResult
from fastmcp.tools.tool_transform import ArgTransform, TransformedTool, forward_raw

from kyckr_mcp.client import KyckrApiError
from kyckr_mcp.openapi.routes import MCP_NAMES

JsonObject = dict[str, object]


def payload(result: ToolResult) -> object:
    structured = result.structured_content
    assert structured is not None, "generated tool returned no structured result"
    return structured.get("result", structured)


def success_response(value: object) -> JsonObject:
    if isinstance(value, dict):
        return {"success": True, **cast(JsonObject, value)}
    return {"success": True, "data": value}


def error_response(error: BaseException) -> JsonObject:
    cause = error.__cause__
    if isinstance(cause, KyckrApiError):
        error = cause
    if isinstance(error, KyckrApiError):
        response: JsonObject = {"success": False, "statusCode": error.status, "message": str(error)}
        if error.correlation_id:
            response["correlationId"] = error.correlation_id
        return response
    return {"success": False, "message": str(error)}


def envelope_output_schema(tool: Tool) -> dict[str, object]:
    parent_schema = cast(dict[str, object], tool.output_schema or {})
    properties: dict[str, object] = {
        "success": {"type": "boolean"},
        "statusCode": {"type": "integer"},
        "message": {"type": "string"},
        "correlationId": {"type": "string"},
        "customerReference": {"type": "string"},
        "timeStamp": {"type": "string"},
        "details": {"type": "string"},
        "cost": {"type": "object"},
    }
    parent_properties = parent_schema.get("properties")
    result_schema = (
        parent_properties.get("result") if isinstance(parent_properties, Mapping) else None
    )
    if isinstance(result_schema, Mapping):
        direct_properties = result_schema.get("properties")
        if isinstance(direct_properties, Mapping) and "data" in direct_properties:
            properties["data"] = direct_properties["data"]
        all_of = result_schema.get("allOf")
        if isinstance(all_of, list):
            for item in all_of:
                if isinstance(item, Mapping):
                    item_properties = item.get("properties")
                    if isinstance(item_properties, Mapping) and "data" in item_properties:
                        properties["data"] = item_properties["data"]
    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "required": ["success"],
        "additionalProperties": True,
    }
    if "$defs" in parent_schema:
        schema["$defs"] = parent_schema["$defs"]
    return schema


async def forward_response(arguments: Mapping[str, object]) -> JsonObject:
    try:
        return success_response(payload(await forward_raw(**arguments)))
    except (KyckrApiError, ToolError) as exc:
        return error_response(exc)


async def forward_payload(arguments: Mapping[str, object]) -> object:
    result = await forward_raw(**arguments)
    return payload(result)


async def wrap_tool(
    mcp: FastMCP,
    operation_id: str,
    fn: Callable[..., object],
    renames: dict[str, str] | None = None,
) -> None:
    generated_name = MCP_NAMES[operation_id]
    generated = await mcp.get_tool(generated_name)
    assert generated is not None, f"generated tool {generated_name} is missing"

    declared = set(inspect.signature(fn).parameters)
    transform_args = {
        argument: (
            ArgTransform(name=(renames or {})[argument])
            if argument in (renames or {})
            else ArgTransform(hide=True)
        )
        for argument in generated.parameters.get("properties", {})
        if argument not in declared or argument in (renames or {})
    }
    description = inspect.getdoc(fn)
    assert description, f"{fn.__name__} needs a docstring"

    mcp.disable(names={generated_name}, components={"tool"})
    mcp.add_tool(
        TransformedTool.from_tool(
            generated,
            name=fn.__name__,
            description=" ".join(description.split()),
            transform_fn=fn,
            transform_args=transform_args,
            output_schema=envelope_output_schema(generated),
        )
    )
