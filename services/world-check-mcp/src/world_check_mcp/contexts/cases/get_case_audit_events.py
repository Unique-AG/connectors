from world_check_mcp.contexts.cases.get_case import get_case
from world_check_mcp.contexts.cases.models import AuditEvent
from world_check_mcp.contexts.cases.models import AuditPage
from world_check_mcp.upstream import GET_CASE_AUDIT_EVENTS
from world_check_mcp.upstream import next_page
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
    pagination: dict[str, object] = {"itemsPerPage": limit}
    if page_reference is not None:
        pagination["pageReference"] = page_reference
    arguments: dict[str, object] = {
        "caseSystemId": resolved.case_system_id,
        "sort": [{"columnName": "eventDate", "order": "DESCENDING"}],
        "pagination": pagination,
    }
    if query is not None:
        arguments["query"] = query
    found = await upstream.call(GET_CASE_AUDIT_EVENTS, **arguments)
    return AuditPage(
        case_system_id=resolved.case_system_id,
        events=[
            AuditEvent(
                id=event.id,
                action_type=event.action_type,
                event_date=event.event_date,
                actioned_by=event.actioned_by_user_name,
            )
            for event in found.results
        ],
        next_page=next_page(found.pagination),
    )
