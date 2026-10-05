"""Firm-wide (or party) activity search via `POST /entity-activities`, the CRM Activity
Explorer's search (it creates nothing). Failure is not an empty result: 404, schema drift, or
a re-verified 401 must surface, and the walk stops before `pageNum × pageSize` passes 10000.
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Literal

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
# Org search returns activity inherited through people; those rows name the person only.
_INHERITED_PARTY_KINDS: frozenset[str] = frozenset({"people", "contacts", "employees"})

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
    """Walk `POST /entity-activities` until the set is exhausted, `max_rows`, or the 10000 wall."""

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
        attendee_ids: Sequence[str] = (),
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
            or bool(attendee_ids)
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
                        attendee_ids=attendee_ids,
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
                resource_type=resource_type,
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
        attendee_ids: Sequence[str],
        include_description: bool,
    ) -> dict[str, object]:
        """JSON:API search body. Built here, never passed through from a caller.

        Date, types, tags, authors, and attendees go under `newFilters`. `filters` is ignored
        by Backstop. A party is `entityId` + `resourceType`, not `associatedWiths`.
        `meeting_call` is sent as the search value `call`.

        An attendee is `PartyBean_<id>` under `type` 0, several values OR. The same id is a
        people, contacts, or employees id. A bare id, email, or name is a 500; another bean
        prefix, or an organization id, silently matches nothing. `type` 1 ignores the values.
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
        if attendee_ids:
            new_filters["attendees"] = [
                {
                    "type": 0,
                    "searchValues": [
                        {"value": f"PartyBean_{attendee_id}"} for attendee_id in attendee_ids
                    ],
                }
            ]
        include_fields = ["associatedWith", "inheritedFrom", "primaryEntity"]
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
        resource_type: SearchType | None,
        activity_tags: Sequence[str],
        total_count: int | None,
        scoped: bool,
    ) -> tuple[tuple[EntityActivityDto, ...], int, dict[str, int]]:
        """Drop rows that show an ignored filter. Person-only rows on a party search are kept.

        A non-party search whose totalCount is 10000 is reported as `total_count`.
        """
        check_types = bool(types) and frozenset(types) != frozenset(ENTITY_ACTIVITY_TYPES)
        allowed_types = {_TYPE_LABELS[token] for token in types if token in _TYPE_LABELS}
        requested_tags = {tag for tag in activity_tags if tag}
        date_violations = 0
        type_violations = 0
        tag_violations = 0
        readable = 0
        party_hits = 0
        party_contradictions = 0
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
            if party_id is not None:
                relation = self._party_relation(attributes, party_id, resource_type)
                if relation == "hit":
                    party_hits += 1
                elif relation == "contradict":
                    party_contradictions += 1
            if row_violation:
                continue
            row = EntityActivityDto.from_attributes(attributes)
            if row is None:
                unprojectable += 1
                continue
            projected.append(row)

        party_violation = (
            party_id is not None and readable > 0 and party_hits == 0 and party_contradictions > 0
        )
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
        if party_id is None and scoped and total_count == MAX_RETRIEVABLE:
            violating["total_count"] = 0
        return tuple(projected), unreadable + unprojectable, violating

    def _party_relation(
        self,
        attributes: EntityActivityAttributes,
        party_id: str,
        resource_type: SearchType | None,
    ) -> Literal["hit", "contradict", "neutral"]:
        """`hit` names the id; `contradict` names another party of the same kind; else `neutral`."""
        refs = (
            *attributes.associated_with,
            *attributes.inherited_from,
            *(() if attributes.primary_entity is None else (attributes.primary_entity,)),
        )
        named = False
        other_party = False
        for ref in refs:
            if ref.resource_id is None:
                continue
            if ref.resource_id == party_id:
                named = True
                continue
            if resource_type == "organizations" and ref.resource_type in _INHERITED_PARTY_KINDS:
                continue
            other_party = True
        if named:
            return "hit"
        if other_party:
            return "contradict"
        return "neutral"

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
