from world_check_mcp.contexts.attribution import AttributionError
from world_check_mcp.contexts.attribution import reviewer_note
from world_check_mcp.contexts.cases import get_case
from world_check_mcp.contexts.pages import all_case_results
from world_check_mcp.contexts.pages import ResultPageError
from world_check_mcp.contexts.passport.errors import PassportError
from world_check_mcp.contexts.passport.models import PassportMrz
from world_check_mcp.contexts.passport.models import PassportVerification
from world_check_mcp.contexts.passport.models import PassportVerificationPlan
from world_check_mcp.contexts.passport.models import PassportVerificationRequest
from world_check_mcp.upstream import Upstream
from world_check_mcp.upstream import VERIFY_PASSPORT

_GUIDANCE = (
    "Inspect get_case_audit_events for the verification. "
    "A new verification requires rescreen_case first. "
    "A matching MRZ is not proof of authenticity or ownership."
)


async def prepare_passport_verification(
    *,
    upstream: Upstream,
    request: PassportVerificationRequest,
    actor: str,
) -> PassportVerificationPlan:
    """The MRZ lines and note a person must approve. This does not write."""
    case = await get_case(upstream=upstream, case=request.case_system_id)
    if "PASSPORT_CHECK" not in case.provider_types:
        raise PassportError("The case is not configured for Passport Check.")
    try:
        results = await all_case_results(upstream=upstream, case_system_id=case.case_system_id)
    except ResultPageError as error:
        raise PassportError(f"{error} No verification was saved.") from error
    lines = tuple(
        PassportMrz(
            result_id=item.result_id,
            mrz_line_1=item.mrz_line_1,
            mrz_line_2=item.mrz_line_2,
            mrz_line_3=item.mrz_line_3,
        )
        for item in results
        if item.provider_type == "PASSPORT_CHECK"
    )
    if not any(line.mrz_line_1 for line in lines):
        raise PassportError(
            "No generated passport MRZ was found. Screen or rescreen the case before verification."
        )
    try:
        note = reviewer_note(note=request.note, actor=actor)
    except AttributionError as error:
        raise PassportError(str(error)) from error
    return PassportVerificationPlan(
        case_system_id=case.case_system_id,
        case_id=case.case_id,
        case_name=case.name,
        mrz_matched=request.mrz_matched,
        note=note,
        lines=lines,
    )


async def apply_passport_verification(
    *,
    upstream: Upstream,
    request: PassportVerificationRequest,
    plan: PassportVerificationPlan,
    actor: str,
) -> PassportVerification:
    """Save an already approved comparison, after reading the case once more."""
    current = await prepare_passport_verification(upstream=upstream, request=request, actor=actor)
    if current != plan:
        raise PassportError(
            "Case or passport results changed during approval. Review and request fresh approval."
        )
    await upstream.call(
        VERIFY_PASSPORT,
        caseSystemId=request.case_system_id,
        mrzMatched=plan.mrz_matched,
        note=plan.note,
    )
    return PassportVerification(
        recorded=True,
        case_system_id=request.case_system_id,
        mrz_matched=plan.mrz_matched,
        note=plan.note,
        guidance=_GUIDANCE,
    )
