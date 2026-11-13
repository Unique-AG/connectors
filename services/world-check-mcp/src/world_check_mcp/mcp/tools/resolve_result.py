from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import InputRequiredResult
from mcp_types import ToolAnnotations
from pydantic import Field

from world_check_mcp import contexts
from world_check_mcp.mcp.approval import ApprovalGate
from world_check_mcp.mcp.approval import resolution_message
from world_check_mcp.mcp.dependencies import get_approvals
from world_check_mcp.mcp.dependencies import get_case_locks
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
    description=(
        "Record a WATCHLIST match decision only after a person approves the exact choice.\n"
        "\n"
        "Decline, cancel, expiry, changed inputs, and a replayed approval save nothing. "
        "Status, risk, and reason must be allowed together by the group's toolkit."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, idempotent_hint=False, destructive_hint=True, open_world_hint=True
    ),
)
@trace_arguments("case", "result_id", "status", "risk")
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
    locks: contexts.CaseLocks = Depends(get_case_locks),
    actor: str = Depends(get_reviewer),
) -> contexts.ResolutionOutcome | InputRequiredResult:
    request = contexts.ResolutionRequest(
        case=case, result_id=result_id, status=status, risk=risk, reason=reason, note=note
    )
    try:
        outcome = await approvals.run(
            ctx,
            request=request,
            actor=actor,
            plan_type=contexts.ResolutionPlan,
            prepare=lambda: contexts.prepare_resolution(
                upstream=upstream, request=request, actor=actor
            ),
            message=resolution_message,
            apply=lambda plan: contexts.apply_resolution(
                upstream=upstream, request=request, plan=plan, actor=actor, locks=locks
            ),
        )
    except contexts.CaseNotFoundError as error:
        raise ToolError(str(error)) from error
    except contexts.ResolutionError as error:
        raise ToolError(str(error)) from error
    return outcome or contexts.ResolutionOutcome(resolved=False, status="cancelled")
