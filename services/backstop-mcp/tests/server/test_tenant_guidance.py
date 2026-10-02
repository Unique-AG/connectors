"""Tenant guidance is appended to published text and never changes a tool's call path."""

import copy
import json
from collections.abc import Callable
from typing import cast

import pytest
from fastmcp import Client, Context, FastMCP
from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from fastmcp.tools import tool as mcp_tool

from backstop_mcp.config import TenantGuidance, TenantGuidanceConfig, ToolGuidance
from backstop_mcp.server.instructions import INSTRUCTIONS
from backstop_mcp.server.tenant_guidance import (
    TENANT_HEADING,
    check_guidance_targets,
    compose_instructions,
    with_tool_guidance,
)
from backstop_mcp.server.tools import TOOLS


def _toy_token() -> str:
    return "injected"


@mcp_tool
async def toy_echo(ctx: Context, label: str, token: str = Depends(_toy_token)) -> str:
    """Echo a label."""
    return f"{token}:{label}:{type(ctx).__name__}"


def _tool(name: str) -> Callable[..., object]:
    return next(fn for fn in TOOLS if fn.__name__ == name)


def _register(fn: Callable[..., object]) -> Tool:
    return FastMCP("tenant-guidance").add_tool(fn)


def _properties(registered: Tool) -> dict[str, object]:
    raw = cast("object", registered.parameters["properties"])
    assert isinstance(raw, dict)
    return {str(key): value for key, value in cast("dict[object, object]", raw).items()}


def _schema(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return {str(key): item for key, item in cast("dict[object, object]", value).items()}


def _without_description(schema: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in schema.items() if key != "description"}


def test_empty_guidance_leaves_core_text_unchanged() -> None:
    tool = _register(_tool("search_opportunities"))
    copied = with_tool_guidance(tool, ToolGuidance())

    assert compose_instructions(INSTRUCTIONS, TenantGuidance()) is INSTRUCTIONS
    assert copied.description == tool.description
    assert copied.parameters == tool.parameters


def test_server_text_is_appended_after_the_heading() -> None:
    guidance = TenantGuidance(server_instructions="Contoso calls a deal a flavor.")

    assert compose_instructions(INSTRUCTIONS, guidance) == (
        f"{INSTRUCTIONS}\n\n{TENANT_HEADING}\nContoso calls a deal a flavor."
    )


def test_a_tool_description_is_appended_to_that_tool_only() -> None:
    target = _register(_tool("search_opportunities"))
    other = _register(_tool("search_organizations"))
    note = "Contoso strategy lives on a custom field."

    updated = with_tool_guidance(target, ToolGuidance(description=note))

    assert updated.description == f"{target.description}\n\n{TENANT_HEADING}\n{note}"
    assert other.description != updated.description
    assert TENANT_HEADING not in (other.description or "")


def test_a_parameter_entry_is_appended_to_that_property_only() -> None:
    tool = _register(_tool("search_opportunities"))
    before = _properties(tool)
    hint = "Flavor is the strategy field."

    updated = with_tool_guidance(tool, ToolGuidance(parameters={"custom_fields": hint}))
    properties = _properties(updated)
    custom_fields = _schema(properties["custom_fields"])
    base = _schema(before["custom_fields"])

    assert custom_fields["description"] == f"{base['description']}\n\n{TENANT_HEADING} {hint}"
    assert _without_description(custom_fields) == _without_description(base)
    assert properties["product"] == before["product"]
    assert updated.parameters.get("required") == tool.parameters.get("required")


def test_the_original_tool_is_unchanged() -> None:
    tool = _register(_tool("search_opportunities"))
    description = tool.description
    parameters = copy.deepcopy(tool.parameters)

    _ = with_tool_guidance(
        tool,
        ToolGuidance(description="Contoso note.", parameters={"product": "Several vehicles."}),
    )

    assert tool.description == description
    assert tool.parameters == parameters


async def test_the_copied_tool_still_runs() -> None:
    mcp = FastMCP("tenant-guidance-call")
    registered = mcp.add_tool(toy_echo)
    copied = with_tool_guidance(
        registered,
        ToolGuidance(description="Contoso note.", parameters={"label": "Use the legal name."}),
    )
    mcp.local_provider.remove_tool(copied.name)
    mcp.add_tool(copied)

    async with Client(mcp) as client:
        result = await client.call_tool("toy_echo", {"label": "Ada"})
        with pytest.raises(ToolError):
            await client.call_tool("toy_echo", {"label": 1})

    payload: object = result.data  # pyright: ignore[reportAny]
    assert payload == "injected:Ada:Context"


def test_unknown_tool_and_parameter_names_stop_startup() -> None:
    tool = _register(toy_echo)
    unknown_tool = TenantGuidance(tools={"not_a_tool": ToolGuidance(description="Contoso note.")})
    unknown_parameter = TenantGuidance(
        tools={"toy_echo": ToolGuidance(parameters={"not_a_param": "Contoso hint."})}
    )

    with pytest.raises(ValueError, match="not_a_tool"):
        check_guidance_targets(unknown_tool, [tool])
    with pytest.raises(ValueError, match="not_a_param"):
        check_guidance_targets(unknown_parameter, [tool])


def test_config_parses_json_and_rejects_a_bad_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BACKSTOP_MCP_TENANT_GUIDANCE", raising=False)
    assert TenantGuidanceConfig().tenant_guidance == TenantGuidance()

    monkeypatch.setenv("BACKSTOP_MCP_TENANT_GUIDANCE", "{}")
    assert TenantGuidanceConfig().tenant_guidance == TenantGuidance()

    for blank in ("", "   "):
        monkeypatch.setenv("BACKSTOP_MCP_TENANT_GUIDANCE", blank)
        assert TenantGuidanceConfig().tenant_guidance == TenantGuidance()

    monkeypatch.setenv(
        "BACKSTOP_MCP_TENANT_GUIDANCE",
        json.dumps(
            {
                "server_instructions": "Contoso vocabulary.",
                "tools": {
                    "search_opportunities": {
                        "description": "Use the Flavor field.",
                        "parameters": {"custom_fields": "Flavor is the strategy field."},
                    }
                },
            }
        ),
    )
    parsed = TenantGuidanceConfig().tenant_guidance
    assert parsed.server_instructions == "Contoso vocabulary."
    assert parsed.tools["search_opportunities"].description == "Use the Flavor field."
    assert (
        parsed.tools["search_opportunities"].parameters["custom_fields"]
        == "Flavor is the strategy field."
    )

    for payload in (
        {"extra": "nope"},
        {"tools": {"search_opportunities": {"extra": "nope"}}},
        {"server_instructions": ""},
        {"server_instructions": "x" * 2501},
        {"tools": {"search_opportunities": {"description": ""}}},
        {"tools": {"search_opportunities": {"description": "x" * 801}}},
        {"tools": {"search_opportunities": {"parameters": {"custom_fields": ""}}}},
        {"tools": {"search_opportunities": {"parameters": {"custom_fields": "x" * 301}}}},
    ):
        monkeypatch.setenv("BACKSTOP_MCP_TENANT_GUIDANCE", json.dumps(payload))
        with pytest.raises(ValueError):
            TenantGuidanceConfig()

    monkeypatch.setenv("BACKSTOP_MCP_TENANT_GUIDANCE", "{")
    with pytest.raises(ValueError, match="BACKSTOP_MCP_TENANT_GUIDANCE"):
        TenantGuidanceConfig()


def test_every_tool_description_accepts_an_overlay() -> None:
    mcp = FastMCP("tenant-guidance-descriptions")
    registered = tuple(mcp.add_tool(fn) for fn in TOOLS)
    guidance = TenantGuidance(
        tools={tool.name: ToolGuidance(description=f"Note for {tool.name}.") for tool in registered}
    )

    check_guidance_targets(guidance, registered)
    for registered_tool in registered:
        note = f"Note for {registered_tool.name}."
        updated = with_tool_guidance(registered_tool, guidance.tools[registered_tool.name])
        assert updated.description is not None
        assert updated.description.endswith(f"{TENANT_HEADING}\n{note}")


def test_every_top_level_property_accepts_parameter_guidance() -> None:
    mcp = FastMCP("tenant-guidance-parameters")
    registered = tuple(mcp.add_tool(fn) for fn in TOOLS)
    hint = "Contoso hint."
    saw_activity_history_request = False

    for registered_tool in registered:
        properties = _properties(registered_tool)
        updated = with_tool_guidance(
            registered_tool,
            ToolGuidance(parameters={name: hint for name in properties}),
        )
        updated_properties = _properties(updated)
        for name, raw_schema in properties.items():
            schema = _schema(raw_schema)
            new_schema = _schema(updated_properties[name])
            base = schema.get("description")
            expected = (
                f"{base}\n\n{TENANT_HEADING} {hint}"
                if isinstance(base, str)
                else f"{TENANT_HEADING} {hint}"
            )
            assert new_schema["description"] == expected
            assert _without_description(new_schema) == _without_description(schema)
            if registered_tool.name == "get_activity_history" and name == "request":
                saw_activity_history_request = True
                assert isinstance(schema.get("$ref"), str)
                assert "description" not in schema
                assert new_schema["$ref"] == schema["$ref"]
                assert new_schema["description"] == f"{TENANT_HEADING} {hint}"

    assert saw_activity_history_request
