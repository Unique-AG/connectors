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
    description=(
        "Record a human comparison of the generated MRZ with the document, only after "
        "approval.\n"
        "\n"
        "Decline, cancel, expiry, changed inputs, and a replayed approval save nothing. A "
        "repeat verification requires rescreen_case first."
    ),
    annotations=ToolAnnotations(
        read_only_hint=False, idempotent_hint=False, destructive_hint=True, open_world_hint=True
    ),
)
@trace_arguments("case", "mrz_matched")
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
    request = contexts.PassportVerificationRequest(case=case, mrz_matched=mrz_matched, note=note)
    try:
        outcome = await approvals.run(
            ctx,
            request=request,
            actor=actor,
            plan_type=contexts.PassportVerificationPlan,
            prepare=lambda: contexts.prepare_passport_verification(
                upstream=upstream, request=request, actor=actor
            ),
            message=passport_message,
            apply=lambda plan: contexts.apply_passport_verification(
                upstream=upstream, request=request, plan=plan, actor=actor
            ),
        )
    except contexts.CaseNotFoundError as error:
        raise ToolError(str(error)) from error
    except contexts.PassportError as error:
        raise ToolError(str(error)) from error
    return outcome or contexts.PassportVerification(recorded=False, status="cancelled")
