"""What a client sees of this MCP, as packages/mcp-architecture/ARCHITECTURE.md requires it."""

from pathlib import Path

from fastmcp import FastMCP
from mcp_architecture import masks_error_details
from mcp_architecture import settings_showing_input_in_errors
from mcp_architecture import tool_surface
from mcp_architecture import tools_with_a_root_combinator
from mcp_architecture import undescribed_tools
from pytest_regressions.file_regression import FileRegressionFixture

SNAPSHOT = Path(__file__).parent / "tool_surface.generated.json"


async def test_every_tool_and_parameter_is_described(server: FastMCP) -> None:
    missing = await undescribed_tools(server)

    assert not missing, f"give these a docstring or a Field(description=...): {missing}"


async def test_the_tools_served_match_their_snapshot(
    server: FastMCP, file_regression: FileRegressionFixture
) -> None:
    """A change to what a client sees shows up here. Accept it with `uv run pytest --regen-all`."""
    file_regression.check(await tool_surface(server), fullpath=SNAPSHOT)


async def test_every_tool_input_schema_is_a_plain_object(server: FastMCP) -> None:
    combined = await tools_with_a_root_combinator(server)

    assert not combined, f"some clients reject these tools: {combined}"


def test_an_unexpected_error_reaches_the_client_without_its_message(server: FastMCP) -> None:
    assert masks_error_details(server), "create the server with mask_error_details=True"


def test_a_settings_error_does_not_print_the_value_it_was_given() -> None:
    shown = settings_showing_input_in_errors("mcp_skeleton")

    assert not shown, f"build their model_config with mcp_configs.shared_config: {shown}"
