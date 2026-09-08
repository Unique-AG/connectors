"""Classification helpers for `test_set.py`.

Kept free of `cursor_sdk` so CI can import them without locking that package.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

DEFAULT_MCP_NAME = "backstop"
MCP_TOOLS = frozenset(
    {
        "get_organization",
        "get_person",
        "list_custom_fields",
        "list_custom_field_groups",
        "list_activity_tags",
        "list_system_users",
        "get_activity_history",
        "get_activity_detail",
        "search_activities",
        "get_opportunities",
        "get_opportunities_by_ids",
        "search_opportunities",
        "get_time_series",
        "get_product",
        "get_product_investors",
        "get_accounts_for_party",
        "get_capital_flows",
        "get_people_for_party",
        "get_tasks_for_party",
    }
)

Verdict = Literal["pass", "partial", "fail", "error"]


@dataclass
class ToolCall:
    name: str
    status: str


@dataclass
class JudgeScore:
    verdict: Literal["pass", "partial", "fail"]
    reason: str
    contradictions: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)


def _as_string_map(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw = cast(dict[object, object], value)
    out: dict[str, object] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            return None
        out[key] = item
    return out


def _is_mcp_tool(name: str) -> bool:
    """True for a Backstop MCP tool or the Cursor `mcp` gateway that fronts them."""
    normalized = name.lower().replace("-", "_")
    if normalized in {DEFAULT_MCP_NAME.lower().replace("-", "_"), "mcp"}:
        return True
    return any(normalized == tool or normalized.endswith(f"_{tool}") for tool in MCP_TOOLS)


def _tool_call_name(message: object) -> str:
    """Cursor's local agent reports the MCP gateway as `mcp`, not the Backstop tool.

    `tools=["mcp"]` in `_answer_options` is that gateway. The inner Backstop name, when
    present, is in `args` (`toolName` / `tool` / …). Prefer that so the judge sees
    `get_accounts_for_party` instead of `(none)`.
    """
    name = getattr(message, "name", "")
    if not isinstance(name, str) or not name:
        return ""
    inner = _inner_mcp_tool_name(getattr(message, "args", None))
    return inner or name


def _inner_mcp_tool_name(args: object) -> str:
    mapped = _as_string_map(args)
    if mapped is None:
        return ""
    for key in ("toolName", "tool_name", "tool", "name"):
        value = mapped.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _split_tools(calls: Sequence[ToolCall]) -> tuple[list[str], list[str]]:
    mcp_tools: list[str] = []
    other: list[str] = []
    seen: set[str] = set()
    for call in calls:
        if call.status == "running" or call.name in seen:
            continue
        seen.add(call.name)
        if _is_mcp_tool(call.name):
            mcp_tools.append(call.name)
        else:
            other.append(call.name)
    return mcp_tools, other


def _verdict(
    *,
    run_status: str,
    mcp_tools: Sequence[str],
    other_tools: Sequence[str],
    judge: JudgeScore | None,
    answer: str,
) -> Verdict:
    if run_status != "finished":
        return "error"
    if other_tools:
        return "fail"
    if not mcp_tools:
        return "fail"
    if not answer.strip():
        return "fail"
    if judge is None:
        return "pass"
    return judge.verdict
