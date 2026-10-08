"""Append a deployment's tenant guidance to the shipped tool documentation."""

from collections.abc import Sequence
from typing import cast

from fastmcp.tools import Tool

from backstop_mcp.config import TenantGuidance, ToolGuidance

TENANT_HEADING = "This firm's Backstop setup:"


def compose_instructions(base: str, guidance: TenantGuidance) -> str:
    """`base` unchanged when there is no tenant text; otherwise base + heading + text."""
    text = guidance.server_instructions
    if text is None:
        return base
    return f"{base}\n\n{TENANT_HEADING}\n{text}"


def check_guidance_targets(guidance: TenantGuidance, tools: Sequence[Tool]) -> None:
    """Raise ValueError naming every unknown tool or parameter in the overlay.

    A typo in a deployment overlay must stop startup, not silently drop the tenant's text.
    The message lists the valid names for whatever was wrong.
    """
    by_name = {tool.name: tool for tool in tools}
    problems: list[str] = []
    unknown_tools = sorted(name for name in guidance.tools if name not in by_name)
    if unknown_tools:
        listed = ", ".join(repr(name) for name in unknown_tools)
        valid = ", ".join(sorted(by_name))
        problems.append(f"unknown tool(s) {listed}; valid tools: {valid}")
    for name in sorted(guidance.tools):
        tool = by_name.get(name)
        if tool is None:
            continue
        properties = _properties(tool)
        unknown_params = sorted(
            param for param in guidance.tools[name].parameters if param not in properties
        )
        if unknown_params:
            listed = ", ".join(repr(param) for param in unknown_params)
            valid = ", ".join(sorted(properties)) or "(none)"
            problems.append(f"unknown parameter(s) {listed} on {name}; valid parameters: {valid}")
    if problems:
        raise ValueError("tenant guidance: " + "; ".join(problems))


def with_tool_guidance(tool: Tool, guidance: ToolGuidance) -> Tool:
    """A copy of `tool` whose description and named parameters carry the tenant text."""
    description = tool.description
    if guidance.description is not None:
        assert description, "a registered tool publishes a description"
        description = f"{description}\n\n{TENANT_HEADING}\n{guidance.description}"
    properties = _properties(tool)
    parameters = {
        **tool.parameters,
        "properties": {
            name: _with_param_text(schema, guidance.parameters.get(name))
            for name, schema in properties.items()
        },
    }
    return tool.model_copy(update={"description": description, "parameters": parameters})


def _properties(tool: Tool) -> dict[str, object]:
    raw = cast("object", tool.parameters["properties"])
    assert isinstance(raw, dict), "a registered tool publishes parameters.properties"
    return {str(key): value for key, value in cast("dict[object, object]", raw).items()}


def _with_param_text(schema: object, text: str | None) -> object:
    if text is None:
        return schema
    assert isinstance(schema, dict), "a published property schema is an object"
    fields = {str(key): value for key, value in cast("dict[object, object]", schema).items()}
    base = fields.get("description")
    if isinstance(base, str):
        description = f"{base}\n\n{TENANT_HEADING} {text}"
    else:
        description = f"{TENANT_HEADING} {text}"
    return {**fields, "description": description}
