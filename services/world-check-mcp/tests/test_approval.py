from contextlib import suppress
import logging
from types import SimpleNamespace
from typing import cast

from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context
from key_value.aio.stores.memory import MemoryStore
from mcp_configs import ElicitationSettings
from mcp_types import ElicitRequest
from mcp_types import ElicitResult
from mcp_types import InputRequiredResult
from pydantic import SecretStr
import pytest

from world_check_mcp.contexts import PassportVerificationPlan
from world_check_mcp.contexts import PassportVerificationRequest
from world_check_mcp.mcp.approval import ApprovalGate
from world_check_mcp.mcp.approval import request_state_security


def _request(*, matched: bool = True) -> PassportVerificationRequest:
    return PassportVerificationRequest(case="sys-1", mrz_matched=matched, note="")


def _plan() -> PassportVerificationPlan:
    return PassportVerificationPlan(
        case_system_id="sys-1",
        case_id="ext-1",
        case_name="Ada",
        mrz_matched=True,
        note="MCP reviewer: ada",
        lines=(),
    )


def _gate(*, ttl_seconds: float, store: MemoryStore | None = None) -> ApprovalGate:
    return ApprovalGate(store=store or MemoryStore(), ttl_seconds=ttl_seconds)


def _as_context(value: object) -> Context:
    return cast(Context, value)


def _connection() -> Context:
    connection = SimpleNamespace(protocol_version="2026-07-28")
    return _as_context(SimpleNamespace(request_context=connection))


async def test_approval_is_single_use_and_bound_to_the_inputs() -> None:
    gate = _gate(ttl_seconds=120)
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
    assert (
        await gate.take(
            accepted, request=_request(), actor="ada", plan_type=PassportVerificationPlan
        )
        == _plan()
    )
    with pytest.raises(ToolError, match="already used"):
        await gate.take(
            accepted, request=_request(), actor="ada", plan_type=PassportVerificationPlan
        )


async def test_a_declined_approval_is_consumed_without_a_plan() -> None:
    gate = _gate(ttl_seconds=120)
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
    assert (
        await gate.take(
            declined, request=_request(), actor="ada", plan_type=PassportVerificationPlan
        )
        is None
    )
    with pytest.raises(ToolError, match="already used"):
        await gate.take(
            declined, request=_request(), actor="ada", plan_type=PassportVerificationPlan
        )


async def test_changed_inputs_do_not_consume_the_approval() -> None:
    gate = _gate(ttl_seconds=120)
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
        await gate.take(
            changed,
            request=_request(matched=False),
            actor="ada",
            plan_type=PassportVerificationPlan,
        )
    assert (
        await gate.take(
            changed, request=_request(), actor="ada", plan_type=PassportVerificationPlan
        )
        == _plan()
    )


async def test_an_expired_approval_cannot_be_used() -> None:
    gate = _gate(ttl_seconds=0)
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
        await gate.take(
            expired, request=_request(), actor="ada", plan_type=PassportVerificationPlan
        )


def _extra(record: logging.LogRecord, *names: str) -> tuple[object, ...]:
    return tuple(cast(object, record.__dict__[name]) for name in names)


async def _take(
    gate: ApprovalGate, *, answer: ElicitResult, request: PassportVerificationRequest
) -> None:
    asked = await gate.ask(
        _connection(), request=_request(), plan=_plan(), actor="ada", message="Save?"
    )
    assert isinstance(asked, InputRequiredResult)
    answered = _as_context(
        SimpleNamespace(request_state=asked.request_state, input_responses={"approval": answer})
    )
    with suppress(ToolError):
        await gate.take(answered, request=request, actor="ada", plan_type=PassportVerificationPlan)


async def test_every_approval_outcome_is_logged_with_its_case(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="world_check_mcp.mcp.approval")
    approve = ElicitResult(action="accept", content={"approve": True})
    await _take(_gate(ttl_seconds=120), answer=approve, request=_request())
    await _take(_gate(ttl_seconds=120), answer=ElicitResult(action="decline"), request=_request())
    await _take(_gate(ttl_seconds=0), answer=approve, request=_request())
    await _take(_gate(ttl_seconds=120), answer=approve, request=_request(matched=False))
    answered = [record for record in caplog.records if record.message == "Approval answered"]
    assert [_extra(record, "outcome", "case") for record in answered] == [
        ("approved", "sys-1"),
        ("declined", "sys-1"),
        ("expired", "sys-1"),
        ("invalid", "sys-1"),
    ]


@pytest.mark.parametrize(
    ("ttl_seconds", "expiry"),
    [(120, "2 minutes"), (60, "1 minute"), (90, "90 seconds")],
)
async def test_the_approval_prompt_states_the_configured_expiry(
    ttl_seconds: float, expiry: str
) -> None:
    asked = await _gate(ttl_seconds=ttl_seconds).ask(
        _connection(), request=_request(), plan=_plan(), actor="ada", message="Save?"
    )
    assert isinstance(asked, InputRequiredResult)
    prompt = (asked.input_requests or {})["approval"]
    assert isinstance(prompt, ElicitRequest)
    assert prompt.params.message == f"Save? Approval expires in {expiry}."


async def test_an_approval_asked_on_one_replica_is_answered_on_another() -> None:
    store = MemoryStore()
    asked = await _gate(ttl_seconds=120, store=store).ask(
        _connection(), request=_request(), plan=_plan(), actor="ada", message="Save?"
    )
    assert isinstance(asked, InputRequiredResult)
    accepted = _as_context(
        SimpleNamespace(
            request_state=asked.request_state,
            input_responses={"approval": ElicitResult(action="accept", content={"approve": True})},
        )
    )
    other = _gate(ttl_seconds=120, store=store)
    assert (
        await other.take(
            accepted, request=_request(), actor="ada", plan_type=PassportVerificationPlan
        )
        == _plan()
    )
    with pytest.raises(ToolError, match="already used"):
        await _gate(ttl_seconds=120, store=store).take(
            accepted, request=_request(), actor="ada", plan_type=PassportVerificationPlan
        )


async def test_a_tampered_request_state_is_refused() -> None:
    tampered = _as_context(
        SimpleNamespace(
            request_state="not an approval",
            input_responses={"approval": ElicitResult(action="accept", content={"approve": True})},
        )
    )
    with pytest.raises(ToolError, match="Request fresh approval"):
        await _gate(ttl_seconds=120).take(
            tampered, request=_request(), actor="ada", plan_type=PassportVerificationPlan
        )


def test_request_state_keys_seal_state_any_replica_opens() -> None:
    settings = ElicitationSettings(request_state_keys=[SecretStr("k" * 32)])
    first_replica = request_state_security(settings)
    second_replica = request_state_security(settings)
    sealed = first_replica.codec.seal(b"approval")
    assert second_replica.codec.unseal(sealed) == b"approval"


def test_request_state_without_keys_stays_with_the_sealing_process() -> None:
    settings = ElicitationSettings(request_state_keys=[])
    sealed = request_state_security(settings).codec.seal(b"approval")
    with pytest.raises(Exception):  # noqa: B017, PT011
        request_state_security(settings).codec.unseal(sealed)
