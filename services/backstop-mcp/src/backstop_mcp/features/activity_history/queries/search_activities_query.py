"""Firm-wide (or party) activity search via `POST /entity-activities`.

The path is in the instance swagger (tag "System - Entity Activities"). The entry is a
create: summary "Create a new entity activity", response 201, and a note that `filterName`,
`entityId`, and `resourceType` are required. It does not create a record. It is the activity
filter the CRM Activity Explorer posts. The example body is placeholders — `filters`,
`newFilters`, and `sorts` are empty objects, and response fields (`results`, `totalCount`)
are mixed into the request. Behaviour below was measured on a live instance. Where swagger
and a response disagree, the response wins.

**Why this path.** One POST returns meetings, calls, notes, emails, and documents together,
already filtered by date window, type, party, tag, and author, and already sorted by
`effectiveDate`. `get_activity_history` is separate per-party REST streams, each paged on
its own. This search is also firm-wide. Those streams hang off one party
(`/{segment}/{id}/activities`), so a question that spans the firm, or more than one client,
has no REST collection to read.

**Failure is not an empty result.** The published contract does not match the search, so a
404, a schema drift, or a 401 that re-verified (`BackstopTransientAuthError`) is not "no
activity exists". `search_activities` names `get_activity_history` — the party-scoped
fallback — in the failure payload. Keep that fallback working. Keep this module's schemas
lenient, and keep `api_responses.py` degrading unreadable fields to `None` rather than
raising.

**Measured behaviour.** Pagination is `pageNum` (1-based) × `pageSize` in the JSON body —
not `paginate` / `links.next`. `pageNum × pageSize > 10000` is HTTP 500, so this module
clamps before the request and returns whatever was already fetched. Success is HTTP 201.

`filters` on this body is ignored (a date window and `associatedWiths` both returned the
firm's newest 10000). The date window goes under `newFilters.effectiveDate` as ISO
timestamps. A party is top-level `entityId` (int) plus `resourceType` (`organizations` /
`people` / `contacts` / `employees`), which also returns activities inherited through that
party's people. `filterName` is not sent. Types, tags, and authors are `newFilters` lists
of one `{searchValues: [{value}]}` object — a bare string is HTTP 500 (`NewFilterDto`), and
a string inside `searchValues` is HTTP 500 (`SearchValue`). Author values also set
`isEmail: true` on the search-value object; the same key on the filter object is HTTP 400.

The tool token `meeting_call` is sent as the search value `call`. Call rows come back as
`type` "Call" and `activityType` "meeting". On one day, no type filter and a types list
that contained `meeting_call` both returned `totalCount` 366, while `email_blast` alone
returned 341, `note` alone returned 4, and `note`/`email`/`meeting`/`call`/`document`/
`task` together returned 23. `note`, `email`, `meeting`, `document`, and `email_blast`
are sent as themselves.

`activityTags` on this body is OR (union). REST `filter[activityTagIds]` is AND. Counts are
permission-filtered: `totalCount` is visible-to-this-credential, not a firm-wide fact, and it
saturates at 10000.
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import date

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
from backstop_mcp.features.activity_history.entity_activity_type import (
    ENTITY_ACTIVITY_TYPES,
    EntityActivityType,
)
from backstop_mcp.features.activity_history.internal_dto import (
    EntityActivitiesFetchDto,
    EntityActivityDto,
)
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.metrics import BACKSTOP_FILTER_IGNORED

logger = logging.getLogger(__name__)

MAX_RETRIEVABLE = 10_000

_TYPE_LABELS: dict[EntityActivityType, str] = {
    "meeting": "meeting",
    "meeting_call": "call",
    "document": "document",
    "email": "email",
    "email_blast": "email blast",
    "note": "note",
}
# Wire values for `newFilters.types`. `meeting_call` is the tool token; Backstop's filter
# value is `call`. Sending `meeting_call` returned the unfiltered totalCount.
_TYPE_FILTER_VALUES: dict[EntityActivityType, str] = {
    "meeting": "meeting",
    "meeting_call": "call",
    "document": "document",
    "email": "email",
    "email_blast": "email_blast",
    "note": "note",
}


class SearchActivitiesQuery:
    """Walk `POST /entity-activities` until the set is exhausted, `max_rows`, or the 10000 wall.

    Swagger calls this a create. It is a search. Read the module docstring before changing
    the request body.
    """

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        start_date: date,
        end_date: date,
        types: Sequence[EntityActivityType] = ENTITY_ACTIVITY_TYPES,
        party_id: str | None = None,
        resource_type: SearchType | None = None,
        activity_tags: Sequence[str] = (),
        authors: Sequence[str] = (),
        include_description: bool = False,
        max_rows: int | None = None,
        page_size: int = 500,
        max_retrievable: int = MAX_RETRIEVABLE,
    ) -> EntityActivitiesFetchDto:
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
        ignored_filters: list[str] = []
        scoped = (
            party_id is not None
            or bool(activity_tags)
            or bool(authors)
            or (bool(types) and frozenset(types) != frozenset(ENTITY_ACTIVITY_TYPES))
        )

        while True:
            if page_num * effective_page_size > max_retrievable:
                ceiling_clamped = True
                break
            if max_rows is not None and len(collected) >= max_rows:
                break
            try:
                document = await self._client.post(
                    "/entity-activities",
                    schema=EntityActivitiesDocument,
                    json=self._request_body(
                        page_num=page_num,
                        page_size=effective_page_size,
                        start_date=start_date,
                        end_date=end_date,
                        types=types,
                        party_id=party_id,
                        resource_type=resource_type,
                        activity_tags=activity_tags,
                        authors=authors,
                        include_description=include_description,
                    ),
                )
            except BackstopRateLimitError:
                raise
            except (BackstopApiError, BackstopResponseSchemaError) as exc:
                if pages_fetched == 0:
                    raise
                logger.warning(
                    "activity_history.entity_activities.later_page_failed_returning_partial",
                    extra={"page_num": page_num, "pages_fetched": pages_fetched},
                    exc_info=exc,
                )
                partial_due_to_error = True
                break
            pages_fetched += 1
            page = document.data.attributes
            if total_count is None:
                total_count = page.total_count
            rows, page_dropped, violating = self._project_rows(
                page.results,
                start_date=start_date,
                end_date=end_date,
                types=types,
                party_id=party_id,
                activity_tags=activity_tags,
                total_count=total_count,
                scoped=scoped,
            )
            self._record_ignored_filters(
                violating,
                total_count=total_count,
                party_id=party_id,
                resource_type=resource_type,
                already_logged=ignored_filters,
            )
            ignored_filters.extend(name for name in violating if name not in ignored_filters)
            dropped += page_dropped
            rows_received += len(page.results)
            collected.extend(rows)
            if any(name != "total_count" for name in violating):
                break
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
            server_filter_ignored=tuple(ignored_filters),
        )

    def _request_body(
        self,
        *,
        page_num: int,
        page_size: int,
        start_date: date,
        end_date: date,
        types: Sequence[EntityActivityType],
        party_id: str | None,
        resource_type: SearchType | None,
        activity_tags: Sequence[str],
        authors: Sequence[str],
        include_description: bool,
    ) -> dict[str, object]:
        """JSON:API search body. Built here, never passed through from a caller.

        Date, types, tags, and authors go under `newFilters`. `filters` is ignored by
        Backstop. A party is `entityId` + `resourceType`, not `associatedWiths`.
        `meeting_call` is sent as the search value `call`.
        """
        new_filters: dict[str, object] = {
            "effectiveDate": {
                "startTimestamp": f"{start_date.isoformat()}T00:00:00",
                "endTimestamp": f"{end_date.isoformat()}T23:59:59",
            }
        }
        if types:
            new_filters["types"] = [
                {
                    "searchValues": [
                        {"value": _TYPE_FILTER_VALUES[activity_type]} for activity_type in types
                    ]
                }
            ]
        if activity_tags:
            new_filters["activityTags"] = [
                {"searchValues": [{"value": tag_id} for tag_id in activity_tags]}
            ]
        if authors:
            new_filters["authors"] = [
                {"searchValues": [{"value": email, "isEmail": True} for email in authors]}
            ]
        include_fields = ["associatedWith"]
        if include_description:
            include_fields = [*include_fields, "description"]
        attributes: dict[str, object] = {
            "pageSize": page_size,
            "pageNum": page_num,
            "sorts": [{"columnName": "effectiveDate", "ascending": False}],
            "newFilters": new_filters,
            "includeFields": include_fields,
        }
        if party_id is not None:
            assert resource_type is not None, "resource_type is required when party_id is set"
            attributes["entityId"] = int(party_id)
            attributes["resourceType"] = resource_type
        if include_description:
            attributes["shouldIncludeDescription"] = True
        return {"data": {"type": "entity-activities", "attributes": attributes}}

    def _project_rows(
        self,
        results: Sequence[dict[str, object]],
        *,
        start_date: date,
        end_date: date,
        types: Sequence[EntityActivityType],
        party_id: str | None,
        activity_tags: Sequence[str],
        total_count: int | None,
        scoped: bool,
    ) -> tuple[tuple[EntityActivityDto, ...], int, dict[str, int]]:
        """Project one page, dropping rows that show Backstop ignored a filter it accepted.

        Returns the kept rows, the unreadable/unprojectable count, and rows-violating per ignored
        filter name (in report order; `total_count` counts 0). A row outside the date window,
        types, or tags is dropped on its own. A party page where no readable row names the
        party drops every readable row. `totalCount` sitting on the 10000 saturation value of a
        scoped search is reported too: the filters narrowed nothing.
        """
        check_types = bool(types) and frozenset(types) != frozenset(ENTITY_ACTIVITY_TYPES)
        allowed_types = {_TYPE_LABELS[token] for token in types if token in _TYPE_LABELS}
        requested_tags = {tag for tag in activity_tags if tag}
        date_violations = 0
        type_violations = 0
        tag_violations = 0
        readable = 0
        party_hits = 0
        unreadable = 0
        unprojectable = 0
        projected: list[EntityActivityDto] = []
        for raw in results:
            attributes = EntityActivityAttributes.safe_model_validate(raw)
            if attributes is None:
                logger.warning("activity_history.entity_activities.row_unreadable")
                unreadable += 1
                continue
            readable += 1
            row_violation = False
            if attributes.effective_date is not None and (
                attributes.effective_date < start_date or attributes.effective_date > end_date
            ):
                date_violations += 1
                row_violation = True
            if check_types and (attributes.type or "").casefold() not in allowed_types:
                type_violations += 1
                row_violation = True
            if requested_tags:
                row_tags = {tag.id for tag in attributes.activity_tags if tag.id}
                if row_tags.isdisjoint(requested_tags):
                    tag_violations += 1
                    row_violation = True
            if party_id is not None and party_id in self._party_ids(attributes):
                party_hits += 1
            if row_violation:
                continue
            row = EntityActivityDto.from_attributes(attributes)
            if row is None:
                unprojectable += 1
                continue
            projected.append(row)

        party_violation = party_id is not None and readable > 0 and party_hits == 0
        if party_violation:
            projected = []
            unprojectable = 0

        violating: dict[str, int] = {}
        if date_violations:
            violating["effective_date"] = date_violations
        if type_violations:
            violating["types"] = type_violations
        if tag_violations:
            violating["activity_tags"] = tag_violations
        if party_violation:
            violating["party"] = readable
        if scoped and total_count == MAX_RETRIEVABLE:
            violating["total_count"] = 0
        return tuple(projected), unreadable + unprojectable, violating

    def _party_ids(self, attributes: EntityActivityAttributes) -> set[str]:
        refs = (
            *attributes.associated_with,
            *attributes.inherited_from,
            *(() if attributes.primary_entity is None else (attributes.primary_entity,)),
        )
        return {ref.resource_id for ref in refs if ref.resource_id is not None}

    def _record_ignored_filters(
        self,
        violating: Mapping[str, int],
        *,
        total_count: int | None,
        party_id: str | None,
        resource_type: SearchType | None,
        already_logged: Sequence[str],
    ) -> None:
        """Warn and count each newly ignored filter, once per name per walk."""
        body_shape = "newFilters+entityId" if party_id is not None else "newFilters"
        for name, rows_violating in violating.items():
            if name in already_logged:
                continue
            logger.warning(
                "activity_history.entity_activities.filter_ignored",
                extra={
                    "filter": name,
                    "rows_violating": rows_violating,
                    "total_count": total_count,
                    "body_shape": body_shape,
                    "party_id": party_id,
                    "resource_type": resource_type,
                    "endpoint": "entity-activities",
                },
            )
            BACKSTOP_FILTER_IGNORED.add(1, {"endpoint": "entity-activities", "filter": name})
