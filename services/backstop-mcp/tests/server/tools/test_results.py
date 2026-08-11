"""`tool_result`: the `exclude_none` opt-in, and the regression guard for its default.

`exclude_none` defaults to `False` so every tool that already shipped keeps its current wire
shape; a payload that wants to drop nulls (activity history) has to ask for it explicitly.
"""

from pydantic import BaseModel

from backstop_mcp.server.tools.results import tool_result
from tests.server.tools.helpers import tool_payload


class _Payload(BaseModel):
    kept: str
    dropped: str | None = None


def test_default_keeps_null_fields() -> None:
    result = tool_result(_Payload(kept="value"))

    payload = tool_payload(result)
    assert payload == {"kept": "value", "dropped": None}


def test_exclude_none_true_drops_null_fields() -> None:
    result = tool_result(_Payload(kept="value"), exclude_none=True)

    payload = tool_payload(result)
    assert payload == {"kept": "value"}
