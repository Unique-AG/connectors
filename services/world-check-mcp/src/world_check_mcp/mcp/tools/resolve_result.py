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
from world_check_mcp.mcp.approval import resolution_message
from world_check_mcp.mcp.dependencies import get_approvals
from world_check_mcp.mcp.dependencies import get_reviewer
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import CaseArgument
from world_check_mcp.upstream import Upstream

Choice = Annotated[
    str,
    Field(description="Id or label from the group's resolution toolkit."),
]
Note = Annotated[
    str,
    Field(max_length=1000, description="Remark saved with the reviewer identity appended."),
]


@tool(
    title="Resolve Result",
    annotations=ToolAnnotations(
        read_only_hint=False, idempotent_hint=False, destructive_hint=True, open_world_hint=True
    ),
)
async def resolve_result(
    case: CaseArgument,
    result_id: Annotated[str, Field(min_length=1, description="resultId of one WATCHLIST match.")],
    status: Annotated[
        Choice,
        Field(description="Status id, label, or POSITIVE, FALSE, POSSIBLE, or UNSPECIFIED."),
    ],
    risk: Choice,
    ctx: Context,
    reason: Annotated[
        Choice | None,
        Field(description="Reason id or label. Required when the toolkit status says so."),
    ] = None,
    note: Note = "",
    upstream: Upstream = Depends(get_upstream),
    approvals: ApprovalGate = Depends(get_approvals),
    actor: str = Depends(get_reviewer),
) -> contexts.ResolutionOutcome | InputRequiredResult:
    """Record a WATCHLIST match decision only after a person approves the exact choice.

    Decline, cancel, expiry, changed inputs, and a replayed approval save nothing.
    Status, risk, and reason must be allowed together by the group's toolkit.
    """
    try:
        return await _resolve(
            case=case,
            result_id=result_id,
            status=status,
            risk=risk,
            reason=reason,
            note=note,
            ctx=ctx,
            upstream=upstream,
            approvals=approvals,
            actor=actor,
        )
    except contexts.CaseNotFoundError as error:
        raise ToolError(str(error)) from error
    except contexts.ResolutionError as error:
        raise ToolError(str(error)) from error


async def _resolve(
    *,
    case: str,
    result_id: str,
    status: str,
    risk: str,
    reason: str | None,
    note: str,
    ctx: Context,
    upstream: Upstream,
    approvals: ApprovalGate,
    actor: str,
) -> contexts.ResolutionOutcome | InputRequiredResult:
    approvals.require_elicitation(ctx)
    found = await contexts.get_case(upstream=upstream, case=case)
    request = contexts.ResolutionRequest(
        case_system_id=found.case_system_id,
        result_id=result_id,
        status=status,
        risk=risk,
        reason=reason,
        note=note,
    )
    if ctx.request_state is None and ctx.input_responses is None:
        plan = await contexts.prepare_resolution(upstream=upstream, request=request, actor=actor)
        decision = await approvals.ask(
            ctx, request=request, plan=plan, actor=actor, message=resolution_message(plan)
        )
    else:
        decision = approvals.take(ctx, request=request, actor=actor)
    if isinstance(decision, InputRequiredResult):
        return decision
    if not isinstance(decision, contexts.ResolutionPlan):
        return contexts.ResolutionOutcome(resolved=False, status="cancelled")
    current = await contexts.get_case(upstream=upstream, case=case)
    if current.case_system_id != request.case_system_id:
        raise ToolError("Case mapping changed during approval. Request fresh approval.")
    return await contexts.apply_resolution(
        upstream=upstream, request=request, plan=decision, actor=actor
    )
