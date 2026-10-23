from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context
from fastmcp.tools import tool
from mcp_types import InputRequiredResult
from mcp_types import ToolAnnotations
from pydantic import Field

from world_check_mcp import contexts
from world_check_mcp.mcp.approval import ApprovalGate
from world_check_mcp.mcp.approval import passport_message
from world_check_mcp.mcp.dependencies import get_approvals
from world_check_mcp.mcp.dependencies import get_reviewer
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import CaseArgument
from world_check_mcp.upstream import Upstream

Note = Annotated[
    str,
    Field(max_length=1000, description="Note saved with the reviewer identity appended."),
]


@tool(
    title="Verify Passport Check",
    annotations=ToolAnnotations(
        read_only_hint=False, idempotent_hint=False, destructive_hint=True, open_world_hint=True
    ),
)
async def verify_passport_check(
    case: CaseArgument,
    mrz_matched: Annotated[
        bool,
        Field(description="True when the generated MRZ matches the document. Not the approval."),
    ],
    ctx: Context,
    note: Note = "",
    upstream: Upstream = Depends(get_upstream),
    approvals: ApprovalGate = Depends(get_approvals),
    actor: str = Depends(get_reviewer),
) -> contexts.PassportVerification | InputRequiredResult:
    """Record a human comparison of the generated MRZ with the document, only after approval.

    Decline, cancel, expiry, changed inputs, and a replayed approval save nothing.
    A repeat verification requires rescreen_case first.
    """
    try:
        return await _verify(
            case=case,
            mrz_matched=mrz_matched,
            note=note,
            ctx=ctx,
            upstream=upstream,
            approvals=approvals,
            actor=actor,
        )
    except contexts.CaseNotFoundError as error:
        raise ToolError(str(error)) from error
    except contexts.PassportError as error:
        raise ToolError(str(error)) from error


async def _verify(
    *,
    case: str,
    mrz_matched: bool,
    note: str,
    ctx: Context,
    upstream: Upstream,
    approvals: ApprovalGate,
    actor: str,
) -> contexts.PassportVerification | InputRequiredResult:
    approvals.require_elicitation(ctx)
    found = await contexts.get_case(upstream=upstream, case=case)
    request = contexts.PassportVerificationRequest(
        case_system_id=found.case_system_id, mrz_matched=mrz_matched, note=note
    )
    if ctx.request_state is None and ctx.input_responses is None:
        plan = await contexts.prepare_passport_verification(
            upstream=upstream, request=request, actor=actor
        )
        decision = await approvals.ask(
            ctx, request=request, plan=plan, actor=actor, message=passport_message(plan)
        )
    else:
        decision = approvals.take(ctx, request=request, actor=actor)
    if isinstance(decision, InputRequiredResult):
        return decision
    if not isinstance(decision, contexts.PassportVerificationPlan):
        return contexts.PassportVerification(recorded=False, status="cancelled")
    current = await contexts.get_case(upstream=upstream, case=case)
    if current.case_system_id != request.case_system_id:
        raise ToolError("Case mapping changed during approval. Request fresh approval.")
    return await contexts.apply_passport_verification(
        upstream=upstream, request=request, plan=decision, actor=actor
    )
