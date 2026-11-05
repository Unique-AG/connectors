import asyncio
from collections.abc import Awaitable, Callable
import logging
from secrets import token_urlsafe
from time import monotonic
from typing import ClassVar, Literal

from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context
from fastmcp.server.elicitation import AcceptedElicitation
from mcp_types import ElicitRequest
from mcp_types import ElicitRequestFormParams
from mcp_types import ElicitResult
from mcp_types import InputRequiredResult
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from world_check_mcp import contexts

_logger = logging.getLogger(__name__)

_PENDING_LIMIT = 256
_APPROVAL_SCHEMA: dict[str, object] = {
    "properties": {
        "approve": {
            "default": False,
            "title": "I approve saving this decision",
            "type": "boolean",
        }
    },
    "required": ["approve"],
    "type": "object",
}
_DECISIONS = {
    "FALSE": "False positive (not the same entity)",
    "TRUE": "Positive match (same entity)",
    "POSITIVE": "Positive match (same entity)",
    "POSSIBLE": "Possible match",
    "UNSPECIFIED": "Unspecified",
    "UNKNOWN": "Unknown",
}


class ApprovalDecision(BaseModel):
    approve: bool = Field(default=False, title="I approve saving this decision")


class _Pending(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    actor: str
    request: contexts.PassportVerificationRequest | contexts.ResolutionRequest
    plan: contexts.PassportVerificationPlan | contexts.ResolutionPlan
    expires_at: float


class ApprovalGate:
    """One approval, bound to the exact inputs and reviewer, kept for `ttl_seconds`."""

    def __init__(self, *, ttl_seconds: float) -> None:
        self._ttl_seconds: float = ttl_seconds
        self._pending: dict[str, _Pending] = {}

    async def run[
        Plan: contexts.PassportVerificationPlan | contexts.ResolutionPlan,
        Outcome,
    ](
        self,
        ctx: Context,
        *,
        request: contexts.PassportVerificationRequest | contexts.ResolutionRequest,
        actor: str,
        plan_type: type[Plan],
        prepare: Callable[[], Awaitable[Plan]],
        message: Callable[[Plan], str],
        apply: Callable[[Plan], Awaitable[Outcome]],
    ) -> Outcome | InputRequiredResult | None:
        """Prepare a write and ask for approval, or take the answer and apply the approved plan.

        None means the reviewer declined, and nothing was written.
        """
        self.require_elicitation(ctx)
        if ctx.request_state is None and ctx.input_responses is None:
            plan = await prepare()
            decision = await self.ask(
                ctx, request=request, plan=plan, actor=actor, message=message(plan)
            )
        else:
            decision = self.take(ctx, request=request, actor=actor)
        if isinstance(decision, InputRequiredResult):
            return decision
        if not isinstance(decision, plan_type):
            return None
        return await apply(decision)

    def require_elicitation(self, ctx: Context) -> None:
        request = ctx.request_context
        if request is None:
            raise ToolError("Human elicitation requires an MCP connection. No write was performed.")
        if request.protocol_version >= "2026-07-28":
            return
        capabilities = ctx.session.client_capabilities
        elicitation = capabilities.elicitation if capabilities is not None else None
        url_only = (
            elicitation is not None and elicitation.form is None and elicitation.url is not None
        )
        if request.protocol_version < "2025-06-18" or elicitation is None or url_only:
            raise ToolError(
                "This decision requires a client supporting form elicitation. "
                "No write was performed."
            )

    async def ask(
        self,
        ctx: Context,
        *,
        request: contexts.PassportVerificationRequest | contexts.ResolutionRequest,
        plan: contexts.PassportVerificationPlan | contexts.ResolutionPlan,
        actor: str,
        message: str,
    ) -> contexts.PassportVerificationPlan | contexts.ResolutionPlan | InputRequiredResult | None:
        self.require_elicitation(ctx)
        message = f"{message} Approval expires in {_duration(self._ttl_seconds)}."
        connection = ctx.request_context
        assert connection is not None, "require_elicitation rejects a missing connection"
        if connection.protocol_version < "2026-07-28":
            return await self._elicit(ctx, plan=plan, case=request.case, message=message)
        nonce = token_urlsafe(32)
        self._remember(nonce=nonce, request=request, plan=plan, actor=actor)
        return InputRequiredResult(
            input_requests={
                "approval": ElicitRequest(
                    params=ElicitRequestFormParams(
                        message=message,
                        requested_schema=_APPROVAL_SCHEMA,
                    )
                )
            },
            request_state=nonce,
        )

    def take(
        self,
        ctx: Context,
        *,
        request: contexts.PassportVerificationRequest | contexts.ResolutionRequest,
        actor: str,
    ) -> contexts.PassportVerificationPlan | contexts.ResolutionPlan | None:
        now = monotonic()
        nonce = ctx.request_state
        pending = self._pending.get(nonce) if nonce else None
        self._drop_expired(now=now)
        expired = pending is not None and pending.expires_at <= now
        if (
            nonce is None
            or pending is None
            or expired
            or pending.actor != actor
            or pending.request != request
        ):
            _log_outcome("expired" if expired else "invalid", case=request.case)
            raise ToolError(
                "Approval is missing, expired, already used, or belongs to different inputs. "
                "Request fresh approval."
            )
        answer = (ctx.input_responses or {}).get("approval")
        if not isinstance(answer, ElicitResult):
            _log_outcome("invalid", case=request.case)
            raise ToolError("A human elicitation response is required. No decision was saved.")
        self._pending.pop(nonce)
        if answer.action != "accept" or (answer.content or {}).get("approve") is not True:
            _log_outcome("declined", case=request.case)
            return None
        _log_outcome("approved", case=request.case)
        return pending.plan

    async def _elicit(
        self,
        ctx: Context,
        *,
        plan: contexts.PassportVerificationPlan | contexts.ResolutionPlan,
        case: str,
        message: str,
    ) -> contexts.PassportVerificationPlan | contexts.ResolutionPlan | None:
        try:
            async with asyncio.timeout(self._ttl_seconds):
                answer = await ctx.elicit(message, response_type=ApprovalDecision)
        except TimeoutError as error:
            _log_outcome("expired", case=case)
            raise ToolError(
                "Approval expired. No write was performed. Request fresh approval."
            ) from error
        if isinstance(answer, AcceptedElicitation) and answer.data.approve is True:
            _log_outcome("approved", case=case)
            return plan
        _log_outcome("declined", case=case)
        return None

    def _remember(
        self,
        *,
        nonce: str,
        request: contexts.PassportVerificationRequest | contexts.ResolutionRequest,
        plan: contexts.PassportVerificationPlan | contexts.ResolutionPlan,
        actor: str,
    ) -> None:
        now = monotonic()
        self._drop_expired(now=now)
        if len(self._pending) >= _PENDING_LIMIT:
            oldest = min(self._pending, key=lambda key: self._pending[key].expires_at)
            self._pending.pop(oldest)
        self._pending[nonce] = _Pending(
            actor=actor,
            request=request,
            plan=plan,
            expires_at=now + self._ttl_seconds,
        )

    def _drop_expired(self, *, now: float) -> None:
        self._pending = {key: item for key, item in self._pending.items() if item.expires_at > now}


def _duration(seconds: float) -> str:
    whole = round(seconds)
    if whole >= 60 and whole % 60 == 0:
        minutes = whole // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{whole} second{'s' if whole != 1 else ''}"


def _log_outcome(
    outcome: Literal["approved", "declined", "expired", "invalid"], *, case: str
) -> None:
    # The tool-call middleware adds the caller's subject, so who decided stays on record.
    _logger.info("Approval answered", extra={"outcome": outcome, "case": case})


def passport_message(plan: contexts.PassportVerificationPlan) -> str:
    outcome = "Matches the document" if plan.mrz_matched else "Does not match the document"
    case_id = plan.case_id or plan.case_system_id
    lines = [
        "Save this passport comparison?",
        "",
        f"- Case: {plan.case_name or 'Unnamed'} ({case_id})",
        f"- Passport MRZ: {outcome}",
        "",
        "Generated MRZ (machine-readable passport lines):",
        "",
    ]
    for item in plan.lines:
        lines.append("```")
        for value in (item.mrz_line_1, item.mrz_line_2, item.mrz_line_3):
            if value:
                lines.append(value)
        lines.append("```")
        lines.append("")
    lines.append(
        "Only approve after comparing these lines with the document at hand. "
        "This does not verify authenticity or ownership."
    )
    return _with_note(lines=lines, note=plan.note)


def resolution_message(plan: contexts.ResolutionPlan) -> str:
    name = plan.submitted_term or "Unnamed match"
    reference = plan.reference_id or plan.result_id
    reason = _decision_label(plan.reason) if plan.reason is not None else "None"
    lines = [
        "Save this World-Check match decision?",
        "",
        f"- Case: {plan.case_name or 'Unnamed'} ({plan.case_id or plan.case_system_id})",
        f"- Match: {name} ({reference})",
        f"- Decision: {_decision_label(plan.status)}",
        f"- Risk: {_decision_label(plan.risk)}",
        f"- Reason: {reason}",
    ]
    return _with_note(lines=lines, note=plan.note)


def _decision_label(choice: contexts.ResolutionChoice) -> str:
    for value in (choice.status_type, choice.label):
        if value is not None and value.upper() in _DECISIONS:
            return _DECISIONS[value.upper()]
    return choice.label


def _with_note(*, lines: list[str], note: str) -> str:
    return "\n".join(
        [
            *lines,
            "",
            "Note to save:",
            "",
            note or "(No note)",
            "",
            "To save, tick the approval box and select Confirm. "
            "Decline leaves the record unchanged.",
            "",
            "Saved in LSEG using the shared service account, with your reviewer identity "
            "appended to the note.",
        ]
    )
