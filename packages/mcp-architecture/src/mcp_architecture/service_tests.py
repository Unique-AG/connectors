"""The tests `plugin.py` adds to an MCP's `tests/`. They use the MCP's own `server` fixture."""

import pytest
from fastmcp import FastMCP
from pytest_regressions.file_regression import FileRegressionFixture

from mcp_architecture.rules import RULES, Rule
from mcp_architecture.service import Service
from mcp_architecture.tools import tool_surface, undescribed_tools

SNAPSHOT = "tool_surface.generated.json"


@pytest.mark.parametrize("rule", RULES, ids=[rule.name for rule in RULES])
def test_the_service_keeps_the_architecture(rule: Rule, request: pytest.FixtureRequest) -> None:
    problems = rule.check(Service(request.config.rootpath))

    assert not problems, f"{rule.summary}\n" + "\n".join(problems)


@pytest.mark.asyncio
async def test_every_tool_and_parameter_is_described(server: FastMCP) -> None:
    missing = await undescribed_tools(server)

    assert not missing, f"give these a docstring or a Field(description=...): {missing}"


@pytest.mark.asyncio
async def test_the_tools_served_match_their_snapshot(
    server: FastMCP, file_regression: FileRegressionFixture, request: pytest.FixtureRequest
) -> None:
    """A tool served from the spec changes with it, so a spec refresh shows up here."""
    snapshot = request.config.rootpath / "tests" / SNAPSHOT
    file_regression.check(await tool_surface(server), fullpath=snapshot)
