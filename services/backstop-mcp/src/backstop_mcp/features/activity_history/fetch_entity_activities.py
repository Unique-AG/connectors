"""Firm-wide (or party) activity search via `POST /entity-activities`.

UNDOCUMENTED ENDPOINT — deliberately. Read this before changing anything here.

**Where it came from.** It is not in the Backstop swagger. It was found by navigating the
Backstop web app's Activity Explorer with the browser network tab open: the screen a Backstop
user actually uses to answer "what happened with this client", and this is the single call it
makes. Nothing about it is inferred from the published API docs, which do not mention it; every
behaviour recorded below was measured against a live instance. That is also the only way to
verify a change to this module — the swagger cannot confirm or deny any of it.

**Why we use it anyway.** It is dramatically faster than the documented route, and it answers
questions the documented route cannot answer at all:

- One POST returns meetings, calls, notes, emails and documents together, already filtered by
  date window, type, party, tag and author, and already sorted by `effectiveDate`. The
  documented equivalent (`get_activity_history`) is four separate per-party REST streams, each
  paged on its own, then merged and sorted here — many requests per answer instead of one.
- It searches **firm-wide**. The REST streams hang off one party (`/{segment}/{id}/activities`),
  so without this endpoint "what did the firm do last quarter", "what did this colleague log",
  and any question spanning more than one client are simply unanswerable.
- Those are the questions clients want Backstop to answer. This endpoint, and the account table
  in `accounts/queries/get_holdings_query.py`, are the two undocumented calls the product leans on
  hardest; treat both as load-bearing rather than as shortcuts to clean up later.

**What we owe for that.** An undocumented endpoint can change or be absent without notice, so
callers must never treat its failure as "no activity exists": `search_activities` catches a 404,
a schema drift, or a 401 that re-verified (`BackstopTransientAuthError`) and names
`get_activity_history` — the documented, party-scoped fallback — in the failure payload. Keep
that fallback working. Keep this module's schemas lenient, and keep `api_responses.py`
degrading unreadable fields to `None` rather than raising.

**Measured behaviour.** The swagger name would call it a create; it is a search. Pagination is
`pageNum` (1-based) × `pageSize` in the JSON body — not `paginate` / `links.next`.
`pageNum × pageSize > 10000` is HTTP 500, so this module clamps **before** the request and
returns whatever was already fetched.

`activityTags` on this body is OR (union). REST `filter[activityTagIds]` is AND. Counts are
permission-filtered: `totalCount` is visible-to-this-credential, not a firm-wide fact, and it
saturates at 10000.
"""

import logging
from collections.abc import Sequence
from datetime import date
from typing import Literal

from pydantic import ValidationError

from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopClient,
    BackstopRateLimitError,
    BackstopResponseSchemaError,
)
from backstop_mcp.features.activity_history.api_responses import (
    EntityActivitiesDocument,
    EntityActivityAttributes,
)
from backstop_mcp.features.activity_history.internal_dto import (
    EntityActivitiesFetchDto,
    EntityActivityDto,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ENTITY_ACTIVITY_TYPES",
    "MAX_RETRIEVABLE",
    "EntityActivityType",
    "entity_activities_request_body",
    "fetch_entity_activities",
    "party_bean",
]

EntityActivityType = Literal["meeting_call", "meeting", "document", "email", "email_blast", "note"]
ENTITY_ACTIVITY_TYPES: tuple[EntityActivityType, ...] = (
    "meeting_call",
    "meeting",
    "document",
    "email",
    "email_blast",
    "note",
)

_PATH = "/entity-activities"
_RESOURCE_TYPE = "entity-activities"
MAX_RETRIEVABLE = 10_000
_PAGE_SIZE = 500
_INCLUDE_ASSOCIATED_WITH = "associatedWith"
_INCLUDE_DESCRIPTION = "description"


def party_bean(party_id: str) -> str:
    """The `associatedWiths` encoding this endpoint actually filters on."""
    return f"PartyBean_{party_id}"


def _timestamp(day: date, *, end: bool) -> str:
    """Naive local-day bound, matching the measured request bodies."""
    clock = "T23:59:59" if end else "T00:00:00"
    return f"{day.isoformat()}{clock}"


def entity_activities_request_body(
    *,
    page_num: int,
    page_size: int,
    start_date: date,
    end_date: date,
    types: Sequence[EntityActivityType],
    associated_withs: Sequence[str],
    activity_tags: Sequence[str],
    authors: Sequence[str],
    include_description: bool,
) -> dict[str, object]:
    """JSON:API search body. Built here, never passed through from a caller."""
    filters: dict[str, object] = {
        "effectiveDate": {
            "startTimestamp": _timestamp(start_date, end=False),
            "endTimestamp": _timestamp(end_date, end=True),
        }
    }
    if types:
        filters["types"] = list(types)
    if associated_withs:
        filters["associatedWiths"] = list(associated_withs)
    if activity_tags:
        filters["activityTags"] = list(activity_tags)
    if authors:
        filters["authors"] = [{"searchValue": email, "isEmail": True} for email in authors]
    include_fields = [_INCLUDE_ASSOCIATED_WITH]
    if include_description:
        include_fields = [*include_fields, _INCLUDE_DESCRIPTION]
    attributes: dict[str, object] = {
        "pageSize": page_size,
        "pageNum": page_num,
        "sorts": [{"columnName": "effectiveDate", "ascending": False}],
        "filters": filters,
        "includeFields": include_fields,
    }
    if include_description:
        attributes["shouldIncludeDescription"] = True
    return {"data": {"type": _RESOURCE_TYPE, "attributes": attributes}}


def _project_rows(
    results: Sequence[dict[str, object]],
) -> tuple[tuple[EntityActivityDto, ...], int]:
    projected: list[EntityActivityDto] = []
    dropped = 0
    for raw in results:
        try:
            attributes = EntityActivityAttributes.model_validate(raw)
        except ValidationError:
            logger.warning("activity_history.entity_activities.row_unreadable")
            dropped += 1
            continue
        row = EntityActivityDto.from_attributes(attributes)
        if row is None:
            dropped += 1
            continue
        projected.append(row)
    return tuple(projected), dropped


async def fetch_entity_activities(
    client: BackstopClient,
    *,
    start_date: date,
    end_date: date,
    types: Sequence[EntityActivityType] = ENTITY_ACTIVITY_TYPES,
    associated_withs: Sequence[str] = (),
    activity_tags: Sequence[str] = (),
    authors: Sequence[str] = (),
    include_description: bool = False,
    max_rows: int | None = None,
    page_size: int = _PAGE_SIZE,
    max_retrievable: int = MAX_RETRIEVABLE,
) -> EntityActivitiesFetchDto:
    """Walk `POST /entity-activities` until the set is exhausted, `max_rows`, or the 10000 wall.

    The endpoint is an undocumented UI search — read the module docstring before changing this,
    including for what "verified" has to mean here.
    """
    effective_page_size = page_size if max_rows is None else min(page_size, max_rows)
    collected: list[EntityActivityDto] = []
    dropped = 0
    rows_received = 0
    pages_fetched = 0
    ceiling_clamped = False
    exhausted = False
    partial_due_to_error = False
    total_count: int | None = None
    page_num = 1

    while True:
        if page_num * effective_page_size > max_retrievable:
            ceiling_clamped = True
            break
        if max_rows is not None and len(collected) >= max_rows:
            break
        try:
            document = await client.post(
                _PATH,
                schema=EntityActivitiesDocument,
                json=entity_activities_request_body(
                    page_num=page_num,
                    page_size=effective_page_size,
                    start_date=start_date,
                    end_date=end_date,
                    types=types,
                    associated_withs=associated_withs,
                    activity_tags=activity_tags,
                    authors=authors,
                    include_description=include_description,
                ),
            )
        except BackstopRateLimitError:
            raise
        except BackstopApiError, BackstopResponseSchemaError:
            if pages_fetched == 0:
                raise
            logger.warning(
                "activity_history.entity_activities.later_page_failed_returning_partial",
                extra={"page_num": page_num, "pages_fetched": pages_fetched},
            )
            partial_due_to_error = True
            break
        pages_fetched += 1
        page = document.data.attributes
        if total_count is None:
            total_count = page.total_count
        rows, page_dropped = _project_rows(page.results)
        dropped += page_dropped
        rows_received += len(page.results)
        collected.extend(rows)
        if len(page.results) < effective_page_size:
            exhausted = True
            break
        if total_count is not None and len(collected) + dropped >= total_count:
            exhausted = True
            break
        page_num += 1

    kept = tuple(collected)
    truncated_by_row_cap = False
    if max_rows is not None and len(kept) > max_rows:
        kept = kept[:max_rows]
        truncated_by_row_cap = True
    elif max_rows is not None and not exhausted and not partial_due_to_error:
        truncated_by_row_cap = True

    logger.info(
        "activity_history.entity_activities.fetched",
        extra={
            "pages": pages_fetched,
            "returned": len(kept),
            "dropped": dropped,
            "received": rows_received,
            "total_count": total_count,
            "ceiling_clamped": ceiling_clamped,
            "partial_due_to_error": partial_due_to_error,
        },
    )
    return EntityActivitiesFetchDto(
        rows=kept,
        total_count=total_count,
        rows_dropped=dropped,
        rows_received=rows_received,
        pages_fetched=pages_fetched,
        ceiling_clamped=ceiling_clamped,
        truncated_by_row_cap=truncated_by_row_cap,
        partial_due_to_error=partial_due_to_error,
    )
