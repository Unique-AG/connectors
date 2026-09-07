"""Harness classification for `agent-explore/test_set.py`.

Cursor's local agent reports Backstop calls as the `mcp` gateway (`tools=["mcp"]`),
not as `get_accounts_for_party`. Treating that name as leakage made every live
case fail even when the judge passed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_EXPLORE = Path(__file__).resolve().parents[2] / "agent-explore"
if str(_EXPLORE) not in sys.path:
    sys.path.insert(0, str(_EXPLORE))

import test_set  # noqa: E402


class TestMcpGatewayIsNotLeakage:
    def test_mcp_gateway_counts_as_an_mcp_tool(self) -> None:
        assert test_set._is_mcp_tool("mcp")
        assert test_set._is_mcp_tool("backstop")
        assert test_set._is_mcp_tool("get_accounts_for_party")

    def test_non_mcp_tools_do_not(self) -> None:
        assert not test_set._is_mcp_tool("webSearch")
        assert not test_set._is_mcp_tool("shell")

    def test_split_treats_gateway_as_mcp_not_other(self) -> None:
        mcp_tools, other = test_set._split_tools(
            [
                test_set.ToolCall(name="mcp", status="running"),
                test_set.ToolCall(name="mcp", status="completed"),
            ]
        )
        assert mcp_tools == ["mcp"]
        assert other == []

    def test_verdict_is_the_judge_when_only_the_gateway_ran(self) -> None:
        judge = test_set.JudgeScore(verdict="pass", reason="gold facts present")
        assert (
            test_set._verdict(
                run_status="finished",
                mcp_tools=["mcp"],
                other_tools=[],
                judge=judge,
                answer="None in an open CGM account.",
            )
            == "pass"
        )

    def test_inner_tool_name_is_taken_from_gateway_args(self) -> None:
        class _Msg:
            name = "mcp"
            args = {"toolName": "get_accounts_for_party", "party_id": "1"}

        assert test_set._tool_call_name(_Msg()) == "get_accounts_for_party"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("get_organization", True),
        ("backstop_get_organization", True),
        ("task", False),
    ],
)
def test_shipped_tool_names(name: str, expected: bool) -> None:
    assert test_set._is_mcp_tool(name) is expected
