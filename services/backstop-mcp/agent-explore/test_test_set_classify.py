"""Classification helpers for `test_set.py`.

Cursor's local agent reports Backstop calls as the `mcp` gateway (`tools=["mcp"]`),
not as `get_accounts_for_party`. Treating that name as leakage made every live
case fail even when the judge passed.
"""

from __future__ import annotations

import pytest
from test_set_classify import (
    JudgeScore,
    ToolCall,
    _is_mcp_tool,  # pyright: ignore[reportPrivateUsage]
    _split_tools,  # pyright: ignore[reportPrivateUsage]
    _tool_call_name,  # pyright: ignore[reportPrivateUsage]
    _verdict,  # pyright: ignore[reportPrivateUsage]
)


class TestMcpGatewayIsNotLeakage:
    def test_mcp_gateway_counts_as_an_mcp_tool(self) -> None:
        assert _is_mcp_tool("mcp")
        assert _is_mcp_tool("backstop")
        assert _is_mcp_tool("get_accounts_for_party")

    def test_non_mcp_tools_do_not(self) -> None:
        assert not _is_mcp_tool("webSearch")
        assert not _is_mcp_tool("shell")

    def test_split_treats_gateway_as_mcp_not_other(self) -> None:
        mcp_tools, other = _split_tools(
            [
                ToolCall(name="mcp", status="running"),
                ToolCall(name="mcp", status="completed"),
            ]
        )
        assert mcp_tools == ["mcp"]
        assert other == []

    def test_verdict_is_the_judge_when_only_the_gateway_ran(self) -> None:
        judge = JudgeScore(verdict="pass", reason="gold facts present")
        assert (
            _verdict(
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
            name: str = "mcp"
            args: dict[str, str] = {"toolName": "get_accounts_for_party", "party_id": "1"}

        assert _tool_call_name(_Msg()) == "get_accounts_for_party"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("get_organization", True),
        ("backstop_get_organization", True),
        ("task", False),
    ],
)
def test_shipped_tool_names(name: str, expected: bool) -> None:
    assert _is_mcp_tool(name) is expected
