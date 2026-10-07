"""Firm-wide (or party) activity search via `POST /entity-activities`, the CRM Activity
Explorer's search (it creates nothing). Failure is not an empty result: 404, schema drift, or
a re-verified 401 must surface. Backstop 500s past offset 10000, so the walk stops before
`pageNum × pageSize` passes it. A rows search stops once it holds at least `min_result_size`
rows and reports the offset to resume from (see `run`).
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import date
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

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
from backstop_mcp.features.collection_scan import SearchCursor, continuation
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.metrics import BACKSTOP_FILTER_IGNORED

logger = logging.getLogger(__name__)

MAX_RETRIEVABLE = 10_000
_SET_PAGE_SIZE = 500
# One person is reachable as people, contacts, or employees; the id is the same in all three.
_PERSON_KINDS: frozenset[str] = frozenset({"people", "contacts", "employees"})
# Ref kinds that name a rival party on a party search. Other refs (opportunities, products,
# accounts) say nothing about the party. Org search also returns activity inherited through
# people, which names the person only, so a person ref does not contradict it.
_CONTRADICTING_KINDS: dict[SearchType, frozenset[str]] = {
    "organizations": frozenset({"organizations"}),
    "people": _PERSON_KINDS,
    "contacts": _PERSON_KINDS,
    "employees": _PERSON_KINDS,
}

_TYPE_LABELS: dict[EntityActivityType, str] = {
    "meeting": "meeting",
    "meeting_call": "call",
    "document": "document",
    "email": "email",
    "email_blast": "email blast",
    "note": "note",
}


class _ProjectedPage(BaseModel):
    """One page checked against the filters: kept rows by index, dropped indices, violations."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    rows: tuple[tuple[int, EntityActivityDto], ...]
    dropped: tuple[int, ...]
    violating: dict[str, int]


class SearchActivitiesQuery:
    """Walk `POST /entity-activities` to the end of the set, `min_result_size` rows, or the wall."""

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
        cursor: str | None = None,
        fingerprint: str | None = None,
        min_result_size: int | None = None,
        page_size: int | None = None,
        max_retrievable: int = MAX_RETRIEVABLE,
    ) -> EntityActivitiesFetchDto:
        """Read whole pages until at least `min_result_size` rows are kept; `None` reads the set.

        The search sorts on effective date, then id, so the order is the same on every request
        and an offset resumes exactly. A rows call that stops before the end hands back a
        `continuation` at the offset after its last page. Resuming by date window instead was
        probed and rejected: Backstop sorts on the UTC instant but filters on the local day, so a
        window cut at a day both repeated and lost rows. A page that shows an ignored filter, a
        failed later page, or the 10000 wall ends the walk without a `continuation`.

        `page_size` defaults to `min_result_size`, so a rows call returns fewer than two pages
        of rows; a whole-set read pages by 500. `fingerprint` ties the cursor to one search's
        arguments; without it no `continuation` is issued (a one-row lookup has nothing to
        resume).
        """
        if page_size is None:
            page_size = _SET_PAGE_SIZE if min_result_size is None else min_result_size
        assert min_result_size is None or min_result_size > 0, "min_result_size must be positive"
        assert cursor is None or fingerprint is not None, "a cursor is checked by fingerprint"
        resume = (
            None
            if cursor is None or fingerprint is None
            else SearchCursor.decode(cursor, fingerprint=fingerprint, collections=1)
        )
        start_offset = 0 if resume is None else resume.offsets[0]
        collected: list[EntityActivityDto] = []
        dropped = 0
        rows_received = 0
        pages_fetched = 0
        ceiling_clamped = False
        partial_due_to_error = False
        total_count: int | None = None
        next_offset: int | None = None
        page_num = start_offset // page_size + 1
        ignored_filters: list[str] = []
        scoped = (
            party_id is not None
            or bool(activity_tags)
            or bool(authors)
            or bool(attendee_ids)
            or (bool(types) and frozenset(types) != frozenset(ENTITY_ACTIVITY_TYPES))
        )

        while True:
            if page_num * page_size > max_retrievable:
                ceiling_clamped = True
                break
            try:
                document = await self._client.post(
                    "/entity-activities",
                    schema=EntityActivitiesDocument,
                    json=self._request_body(
                        page_num=page_num,
                        page_size=page_size,
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
            projected = self._project_rows(
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
                projected.violating,
                total_count=total_count,
                party_id=party_id,
                resource_type=resource_type,
                already_logged=ignored_filters,
            )
            ignored_filters.extend(
                name for name in projected.violating if name not in ignored_filters
            )
            page_offset = (page_num - 1) * page_size
            # Records before `start_offset` were read by the call that issued the cursor.
            skip = min(max(0, start_offset - page_offset), len(page.results))
            collected.extend(row for index, row in projected.rows if index >= skip)
            dropped += sum(1 for index in projected.dropped if index >= skip)
            rows_received += len(page.results) - skip
            # A totalCount on the wall is saturated, not the size of the set.
            is_last = len(page.results) < page_size or (
                total_count is not None
                and total_count < max_retrievable
                and page_offset + len(page.results) >= total_count
            )
            if any(name != "total_count" for name in projected.violating) or is_last:
                break
            if min_result_size is not None and len(collected) >= min_result_size:
                next_offset = page_offset + len(page.results)
                # The last record the endpoint will serve: nothing past it to resume into.
                if next_offset >= max_retrievable:
                    ceiling_clamped, next_offset = True, None
                break
            page_num += 1

        logger.info(
            "activity_history.entity_activities.fetched",
            extra={
                "pages": pages_fetched,
                "returned": len(collected),
                "dropped": dropped,
                "received": rows_received,
                "total_count": total_count,
                "start_offset": start_offset,
                "next_offset": next_offset,
                "ceiling_clamped": ceiling_clamped,
                "partial_due_to_error": partial_due_to_error,
            },
        )
        return EntityActivitiesFetchDto(
            rows=tuple(collected),
            total_count=total_count,
            rows_dropped=dropped,
            rows_received=rows_received,
            pages_fetched=pages_fetched,
            ceiling_clamped=ceiling_clamped,
            partial_due_to_error=partial_due_to_error,
            server_filter_ignored=tuple(ignored_filters),
            continuation=(
                None
                if next_offset is None or fingerprint is None
                else continuation(
                    stop_reason="page_full",
                    next_offsets=(next_offset,),
                    fingerprint=fingerprint,
                    rows_returned=len(collected),
                )
            ),
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
        Type tokens are the wire values: `meeting_call` matches exactly the `Call` rows, while
        `call` matched none, so calls never came back. `id` breaks effective-date ties:
        on date alone, paging one 366-row day by 50 skipped and repeated about 30 rows per walk;
        with `id` the walks matched the single 500-row page.

        Attendees, as probed: `PartyBean_<id>` under `type` 0 applies the filter, several
        values OR, for an id taken from people, contacts, or employees alike (one person has
        one id in all three). `PersonBean_`, `ContactBean_`, `EmployeeBean_`, or an
        organization id silently match nothing; a bare id, email, path, or name is a 500.
        `type` 1 ignores the values. A row's `attendees[]` chips carry a name and no id, so
        `_project_rows` cannot re-check this filter the way it re-checks tags.
        """
        new_filters: dict[str, object] = {
            "effectiveDate": {
                "startTimestamp": f"{start_date.isoformat()}T00:00:00",
                "endTimestamp": f"{end_date.isoformat()}T23:59:59",
            }
        }
        if types:
            new_filters["types"] = [
                {"searchValues": [{"value": activity_type} for activity_type in types]}
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
            "sorts": [
                {"columnName": "effectiveDate", "ascending": False},
                {"columnName": "id", "ascending": True},
            ],
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
    ) -> _ProjectedPage:
        """Drop rows that show an ignored filter. Person-only rows on a party search are kept.

        Kept and dropped rows carry their index in `results`, so the walk can resume mid-page.
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
        unreadable: list[int] = []
        unprojectable: list[int] = []
        projected: list[tuple[int, EntityActivityDto]] = []
        for index, raw in enumerate(results):
            attributes = EntityActivityAttributes.safe_model_validate(raw)
            if attributes is None:
                logger.warning("activity_history.entity_activities.row_unreadable")
                unreadable.append(index)
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
                unprojectable.append(index)
                continue
            projected.append((index, row))

        party_violation = (
            party_id is not None and readable > 0 and party_hits == 0 and party_contradictions > 0
        )
        if party_violation:
            projected = []
            unprojectable = []

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
        return _ProjectedPage(
            rows=tuple(projected),
            dropped=tuple(sorted((*unreadable, *unprojectable))),
            violating=violating,
        )

    def _party_relation(
        self,
        attributes: EntityActivityAttributes,
        party_id: str,
        resource_type: SearchType | None,
    ) -> Literal["hit", "contradict", "neutral"]:
        """`hit` names the id; `contradict` names another party of the same kind; else `neutral`.

        Only a ref of a party kind can contradict: an opportunity or product ref next to the
        party is not a sign Backstop ignored `entityId`.
        """
        contradicting_kinds = (
            frozenset[str]() if resource_type is None else _CONTRADICTING_KINDS[resource_type]
        )
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
            if ref.resource_type in contradicting_kinds:
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
        """Warn and count each newly ignored filter, once per name per walk.

        `total_count` (a scoped search on the 10000 ceiling) is only a hint for the model: it
        may be a broad filter, not an ignored one. It logs at info and is not counted, since
        the `backstop_filter_ignored_total` alert fires on any increase.
        """
        body_shape = "newFilters+entityId" if party_id is not None else "newFilters"
        for name, rows_violating in violating.items():
            if name in already_logged:
                continue
            logger.log(
                logging.INFO if name == "total_count" else logging.WARNING,
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
            if name != "total_count":
                BACKSTOP_FILTER_IGNORED.add(1, {"endpoint": "entity-activities", "filter": name})
