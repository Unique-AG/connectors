from types import SimpleNamespace
from typing import cast

from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context
from mcp_types import ElicitResult
from mcp_types import InputRequiredResult
import pytest

from world_check_mcp.contexts import PassportVerificationPlan
from world_check_mcp.contexts import PassportVerificationRequest
from world_check_mcp.mcp.approval import ApprovalGate


def _request(*, matched: bool = True) -> PassportVerificationRequest:
    return PassportVerificationRequest(case_system_id="sys-1", mrz_matched=matched, note="")


def _plan() -> PassportVerificationPlan:
    return PassportVerificationPlan(
        case_system_id="sys-1",
        case_id="ext-1",
        case_name="Ada",
        mrz_matched=True,
        note="MCP reviewer: ada",
        lines=(),
    )


def _as_context(value: object) -> Context:
    return cast(Context, value)


def _connection() -> Context:
    connection = SimpleNamespace(protocol_version="2026-07-28")
    return _as_context(SimpleNamespace(request_context=connection))


async def test_approval_is_single_use_and_bound_to_the_inputs() -> None:
    gate = ApprovalGate()
    asked = await gate.ask(
        _connection(), request=_request(), plan=_plan(), actor="ada", message="Save?"
    )
    assert isinstance(asked, InputRequiredResult)
    nonce = asked.request_state
    assert nonce is not None
    accepted = _as_context(
        SimpleNamespace(
            request_state=nonce,
            input_responses={"approval": ElicitResult(action="accept", content={"approve": True})},
        )
    )
    assert gate.take(accepted, request=_request(), actor="ada") == _plan()
    with pytest.raises(ToolError, match="already used"):
        gate.take(accepted, request=_request(), actor="ada")


async def test_a_declined_approval_is_consumed_without_a_plan() -> None:
    gate = ApprovalGate()
    asked = await gate.ask(
        _connection(), request=_request(), plan=_plan(), actor="ada", message="Save?"
    )
    assert isinstance(asked, InputRequiredResult)
    declined = _as_context(
        SimpleNamespace(
            request_state=asked.request_state,
            input_responses={"approval": ElicitResult(action="decline")},
        )
    )
    assert gate.take(declined, request=_request(), actor="ada") is None
    with pytest.raises(ToolError, match="already used"):
        gate.take(declined, request=_request(), actor="ada")


async def test_changed_inputs_do_not_consume_the_approval() -> None:
    gate = ApprovalGate()
    asked = await gate.ask(
        _connection(), request=_request(), plan=_plan(), actor="ada", message="Save?"
    )
    assert isinstance(asked, InputRequiredResult)
    changed = _as_context(
        SimpleNamespace(
            request_state=asked.request_state,
            input_responses={"approval": ElicitResult(action="accept", content={"approve": True})},
        )
    )
    with pytest.raises(ToolError, match="different inputs"):
        gate.take(changed, request=_request(matched=False), actor="ada")
    assert gate.take(changed, request=_request(), actor="ada") == _plan()


async def test_an_expired_approval_cannot_be_used() -> None:
    gate = ApprovalGate(ttl_seconds=0)
    asked = await gate.ask(
        _connection(), request=_request(), plan=_plan(), actor="ada", message="Save?"
    )
    assert isinstance(asked, InputRequiredResult)
    expired = _as_context(
        SimpleNamespace(
            request_state=asked.request_state,
            input_responses={"approval": ElicitResult(action="accept", content={"approve": True})},
        )
    )
    with pytest.raises(ToolError, match="expired"):
        gate.take(expired, request=_request(), actor="ada")
