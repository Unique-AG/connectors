from world_check_mcp.contexts.attribution import AttributionError
from world_check_mcp.contexts.attribution import reviewer_note
from world_check_mcp.contexts.cases import get_case
from world_check_mcp.contexts.pages import all_case_results
from world_check_mcp.contexts.pages import ResultPageError
from world_check_mcp.contexts.resolution.errors import ResolutionError
from world_check_mcp.contexts.resolution.models import ResolutionChoice
from world_check_mcp.contexts.resolution.models import ResolutionOutcome
from world_check_mcp.contexts.resolution.models import ResolutionPlan
from world_check_mcp.contexts.resolution.models import ResolutionRequest
from world_check_mcp.upstream import GET_RESOLUTION_TOOLKITS_FOR_GROUP
from world_check_mcp.upstream import ResolutionField
from world_check_mcp.upstream import RESOLVE_RESULTS
from world_check_mcp.upstream import ResultWire
from world_check_mcp.upstream import StatusResolutionField
from world_check_mcp.upstream import Upstream


async def prepare_resolution(
    *,
    upstream: Upstream,
    request: ResolutionRequest,
    actor: str,
) -> ResolutionPlan:
    """The match, status, risk, and note a person must approve. This does not write."""
    case = await get_case(upstream=upstream, case=request.case_system_id)
    try:
        results = await all_case_results(upstream=upstream, case_system_id=case.case_system_id)
    except ResultPageError as error:
        raise ResolutionError(f"{error} No resolution was saved.") from error
    match = _match(results=results, result_id=request.result_id)
    toolkits = await upstream.call(GET_RESOLUTION_TOOLKITS_FOR_GROUP, groupId=case.group_id)
    toolkit = toolkits.root.get("WATCHLIST")
    if (
        toolkit is None
        or toolkit.group_id != case.group_id
        or toolkit.provider_type != "WATCHLIST"
        or toolkit.resolution_fields is None
    ):
        raise ResolutionError("The case, result, and resolution toolkit do not match.")
    fields = toolkit.resolution_fields
    status = _one(value=request.status, choices=_statuses(fields=fields.statuses), kind="status")
    risk = _one(value=request.risk, choices=_options(fields=fields.risks), kind="risk")
    reason = (
        _one(value=request.reason, choices=_options(fields=fields.reasons), kind="reason")
        if request.reason
        else None
    )
    rule = (toolkit.resolution_rules or {}).get(status.id)
    if rule is None or risk.id not in rule.risks:
        raise ResolutionError("This status/risk combination is not allowed by the group toolkit.")
    if (rule.reason_required and reason is None) or (
        reason is not None and reason.id not in rule.reasons
    ):
        raise ResolutionError("Supply a reason allowed for this status by the group toolkit.")
    if rule.remark_required and not request.note.strip():
        raise ResolutionError("This resolution status requires a non-empty note.")
    try:
        note = reviewer_note(note=request.note, actor=actor)
    except AttributionError as error:
        raise ResolutionError(str(error)) from error
    return ResolutionPlan(
        case_system_id=case.case_system_id,
        case_id=case.case_id,
        case_name=case.name,
        result_id=request.result_id,
        reference_id=match.reference_id,
        submitted_term=match.submitted_term,
        status=status,
        risk=risk,
        reason=reason,
        note=note,
        rule_risks=tuple(rule.risks),
        rule_reasons=tuple(rule.reasons),
        reason_required=rule.reason_required,
        remark_required=rule.remark_required,
    )


async def apply_resolution(
    *,
    upstream: Upstream,
    request: ResolutionRequest,
    plan: ResolutionPlan,
    actor: str,
) -> ResolutionOutcome:
    """Save an already approved match decision, after reading the case once more."""
    current = await prepare_resolution(upstream=upstream, request=request, actor=actor)
    if current != plan:
        raise ResolutionError(
            "Case, match, or toolkit changed during approval. Review and request fresh approval."
        )
    arguments: dict[str, object] = {
        "caseSystemId": request.case_system_id,
        "resultIds": [request.result_id],
        "statusId": plan.status.id,
        "riskId": plan.risk.id,
        "resolutionRemark": plan.note,
    }
    if plan.reason is not None:
        arguments["reasonId"] = plan.reason.id
    await upstream.call(RESOLVE_RESULTS, **arguments)
    return ResolutionOutcome(
        resolved=True,
        case_system_id=request.case_system_id,
        result_id=request.result_id,
        status_id=plan.status.id,
        risk_id=plan.risk.id,
        reason_id=plan.reason.id if plan.reason is not None else None,
        note=plan.note,
    )


def _match(*, results: list[ResultWire], result_id: str) -> ResultWire:
    found = [item for item in results if item.result_id == result_id]
    if len(found) != 1:
        raise ResolutionError("result_id does not belong to the specified case.")
    match = found[0]
    if match.provider_type != "WATCHLIST":
        raise ResolutionError("This server resolves WATCHLIST results only.")
    return match


def _one(*, value: str, choices: list[ResolutionChoice], kind: str) -> ResolutionChoice:
    folded = value.casefold()
    exact = [choice for choice in choices if choice.id == value]
    matches = exact or [
        choice
        for choice in choices
        if folded == choice.label.casefold()
        or (choice.status_type is not None and folded == choice.status_type.casefold())
    ]
    if len(matches) != 1:
        raise ResolutionError(f"Supply an unambiguous {kind} id or label from get_group_settings.")
    return matches[0]


def _options(*, fields: list[ResolutionField]) -> list[ResolutionChoice]:
    return [ResolutionChoice(id=field.id, label=field.label) for field in fields]


def _statuses(*, fields: list[StatusResolutionField]) -> list[ResolutionChoice]:
    return [
        ResolutionChoice(id=field.id, label=field.label, status_type=field.type) for field in fields
    ]
