from world_check_mcp.contexts.cases.get_case import get_case
from world_check_mcp.contexts.cases.models import AuditEvent
from world_check_mcp.contexts.cases.models import AuditPage
from world_check_mcp.upstream import FilterInput
from world_check_mcp.upstream import GET_CASE_AUDIT_EVENTS_BY_CASE_SYSTEM_ID
from world_check_mcp.upstream import GetCaseAuditEventsByCaseSystemIdPath
from world_check_mcp.upstream import GetCaseAuditEventsByCaseSystemIdRequest
from world_check_mcp.upstream import next_page
from world_check_mcp.upstream import PaginationReferenceRequestInput
from world_check_mcp.upstream import SortCriterionInput
from world_check_mcp.upstream import Upstream


async def get_case_audit_events(
    *,
    upstream: Upstream,
    case: str,
    query: str | None = None,
    limit: int = 25,
    page_reference: str | None = None,
) -> AuditPage:
    """Audit events for one case, newest first. LSEG defaults the window to the last seven days."""
    resolved = await get_case(upstream=upstream, case=case)
    found = await upstream.call(
        GET_CASE_AUDIT_EVENTS_BY_CASE_SYSTEM_ID,
        GetCaseAuditEventsByCaseSystemIdRequest(
            path=GetCaseAuditEventsByCaseSystemIdPath(case_system_id=resolved.case_system_id),
            body=FilterInput(
                query=query,
                sort=[SortCriterionInput(column_name="eventDate", order="DESCENDING")],
                pagination=PaginationReferenceRequestInput(
                    items_per_page=limit, page_reference=page_reference
                ),
            ),
        ),
    )
    return AuditPage(
        case_system_id=resolved.case_system_id,
        events=[
            AuditEvent(
                id=event.id,
                action_type=event.action_type,
                event_date=event.event_date,
                actioned_by=event.actioned_by_user_name,
            )
            for event in found.results or []
        ],
        next_page=next_page(found.pagination),
    )
