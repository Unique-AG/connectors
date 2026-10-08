"""Firm-wide `GET /organizations`: server filters where Backstop accepts them, then in memory.

`filter[name][like]`, `filter[email][eq]`, `filter[otherId][eq]`, and
`filter[matchingDomains][eq]` change `totalResourceCount` on this API. `filter[city]`,
`filter[legalName]`, `filter[website]`, `filter[ria]`, `filter[internalOrganization]`,
`filter[email2]`, and any custom-field field name are `400 Invalid filter field`.
`filter[regularCustomFieldValues][eq]` is recognized and then rejected: Backstop cannot
convert a query-string value into `RegularCustomFieldValueDto`. Those predicates run
after the fetch. `filter[email][eq]` is the primary email only.

Locations come from `include=contactLocations` on the same walk, so a party's other offices
cost no extra request. `filter[contactLocations.city][eq]` matches any of an organization's
locations, but exactly and case-sensitively, with no `like` and no `in`. `city` and `address`
are the only `contactLocations` filter fields; `state`, `country`, `postalCode`,
`locationTitle`, and `isPrimaryLocation` are `400 Invalid filter field`. So the city and the
street address are sent exactly as the caller wrote them, and the rest of the location filter
runs after the fetch.

One call returns one page of matches and a cursor at the next unread record. Backstop sorts
on one field only and returns records that tie on it in a different order between requests,
so offset paging over `sort=name` would repeat or skip organizations sharing a name at page
edges; the walk uses `sort=id`, which pages cleanly. Rows keep that order: re-sorting a page
by name would reorder rows across pages.

A custom-field-only call reads the collection until the page fills or the collection
ends. Large tenants have thousands of organizations; a sparse page carrying
`regularCustomFieldValues` takes seconds, and the per-user gate allows five concurrent
requests, so a call with in-memory predicates requests later pages in parallel.
"""

import logging
from collections.abc import Sequence

from opentelemetry import trace
from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopClient, Included, SinglePage
from backstop_mcp.features.collection_scan import (
    SearchCursor,
    collect_page,
    continuation,
    scan_coverage,
    search_fingerprint,
)
from backstop_mcp.features.custom_fields import (
    CustomFieldMatch,
    normalize_matches,
    satisfies_every,
    stored_custom_field_values,
)
from backstop_mcp.features.includes import ContactLocationResponse
from backstop_mcp.features.org_people.api_responses import LocationResource, OrganizationResource
from backstop_mcp.features.org_people.inputs import LocationFilter
from backstop_mcp.features.org_people.responses import (
    SearchOrganizationRowResponse,
    SearchOrganizationsResolvedResponse,
)
from backstop_mcp.features.org_people.utils import (
    location_filter_params,
    matches_location,
    party_locations,
)
from backstop_mcp.features.ui_links import BuildEntityLinkUtil, OrganizationLinkTarget

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_PAGE_SIZE = 500
# The per-user gate allows five concurrent requests; a sparse in-memory filter uses them.
_SPARSE_CONCURRENCY = 5


class SearchOrganizationsQuery:
    """Walk `GET /organizations` and keep rows that match every predicate."""

    def __init__(
        self, *, client: BackstopClient, build_entity_link_util: BuildEntityLinkUtil
    ) -> None:
        self._client: BackstopClient = client
        self._build_entity_link_util: BuildEntityLinkUtil = build_entity_link_util

    async def run(
        self,
        *,
        name: str | None = None,
        email: str | None = None,
        other_id: str | None = None,
        matching_domain: str | None = None,
        legal_name: str | None = None,
        location_filter: LocationFilter | None = None,
        website: str | None = None,
        ria: bool | None = None,
        internal_organization: bool | None = None,
        custom_fields: Sequence[CustomFieldMatch] = (),
        exclude_custom_fields: bool = False,
        fields: frozenset[str],
        result_size: int,
        cursor: str | None = None,
    ) -> SearchOrganizationsResolvedResponse:
        """One page of matches from the cursor: server filters on the wire, the rest in memory."""
        name = self._text(name)
        email = self._text(email)
        other_id = self._text(other_id)
        matching_domain = self._text(matching_domain)
        legal_name = self._text(legal_name)
        website = self._text(website)
        predicates = normalize_matches(custom_fields)
        should_filter_in_memory = self._has_in_memory_predicate(
            legal_name=legal_name,
            location_filter=location_filter,
            website=website,
            ria=ria,
            internal_organization=internal_organization,
            predicates=predicates,
        )
        fingerprint = search_fingerprint(
            "search_organizations",
            {
                "name": name,
                "email": email,
                "other_id": other_id,
                "matching_domain": matching_domain,
                "legal_name": legal_name,
                "location_filter": location_filter,
                "website": website,
                "ria": ria,
                "internal_organization": internal_organization,
                "custom_fields": predicates,
                "exclude_custom_fields": exclude_custom_fields,
                "fields": sorted(fields),
            },
        )
        start_offset = (
            0
            if cursor is None
            else SearchCursor.decode(cursor, fingerprint=fingerprint, collections=1).offsets[0]
        )
        params = {
            **self._query_params(
                name=name,
                email=email,
                other_id=other_id,
                matching_domain=matching_domain,
                exclude_custom_fields=exclude_custom_fields,
            ),
            **location_filter_params(location_filter),
        }
        dropped = 0

        async def read_at(offset: int) -> SinglePage[OrganizationResource]:
            return await self._client.fetch_page(
                "/organizations",
                schema=OrganizationResource,
                params=params,
                page_size=_PAGE_SIZE,
                offset=offset,
            )

        def select(
            page: SinglePage[OrganizationResource],
        ) -> tuple[tuple[int, SearchOrganizationRowResponse], ...]:
            nonlocal dropped
            matches, page_dropped = self._select(
                page.items,
                Included(page.included),
                legal_name=legal_name,
                location_filter=location_filter,
                website=website,
                ria=ria,
                internal_organization=internal_organization,
                predicates=predicates,
            )
            dropped += page_dropped
            return matches

        with _tracer.start_as_current_span("org_people.query.search_organizations") as span:
            span.set_attribute("memory", should_filter_in_memory)
            span.set_attribute("start_offset", start_offset)
            page = await collect_page(
                read_at=read_at,
                select=select,
                start_offset=start_offset,
                output_page_size=result_size,
                api_page_size=_PAGE_SIZE,
                concurrency=_SPARSE_CONCURRENCY if should_filter_in_memory else 1,
            )
            span.set_attribute("rows_scanned", page.records_scanned)
            span.set_attribute("matched", len(page.rows))
            span.set_attribute("stop_reason", page.stop_reason)
            logger.info(
                "org_people.search.fetched",
                extra={
                    "memory": should_filter_in_memory,
                    "start_offset": start_offset,
                    "rows_scanned": page.records_scanned,
                    "matched": len(page.rows),
                    "dropped": dropped,
                    "total_count": page.total_count,
                    "request_count": page.request_count,
                    "stop_reason": page.stop_reason,
                },
            )
            projected = fields | {"id"}
            if not exclude_custom_fields:
                projected = projected | {"custom_field_values"}
            return SearchOrganizationsResolvedResponse(
                coverage=scan_coverage(
                    rows_scanned=page.records_scanned,
                    visible_count=page.total_count,
                    rows_dropped=dropped,
                    # No ceiling of ours: a page stops when it is full or the collection ends.
                    ceiling=None,
                    ceiling_clamped=False,
                    # Every page is one request: a failed page raises.
                    partial_due_to_error=False,
                ),
                rows=self._project(page.rows, fields=projected),
                continuation=continuation(
                    stop_reason=page.stop_reason,
                    next_offsets=() if page.next_offset is None else (page.next_offset,),
                    fingerprint=fingerprint,
                    rows_returned=len(page.rows),
                ),
            )

    def _query_params(
        self,
        *,
        name: str | None,
        email: str | None,
        other_id: str | None,
        matching_domain: str | None,
        exclude_custom_fields: bool,
    ) -> dict[str, object]:
        wire_fields = [
            "name",
            "legalName",
            "email",
            "city",
            "country",
            "state",
            "postalCode",
            "streetAddress",
            "locationTitle",
            "website",
            "otherId",
            "matchingDomains",
            "ria",
            "internalOrganization",
        ]
        if not exclude_custom_fields:
            wire_fields.append("regularCustomFieldValues")
        params: dict[str, object] = {
            "sort": "id",
            "include": "contactLocations",
            "fields[organizations]": ",".join(wire_fields),
        }
        if name is not None:
            params["filter[name][like]"] = name
        if email is not None:
            params["filter[email][eq]"] = email
        if other_id is not None:
            params["filter[otherId][eq]"] = other_id
        if matching_domain is not None:
            params["filter[matchingDomains][eq]"] = matching_domain
        return params

    def _select(
        self,
        resources: Sequence[OrganizationResource],
        included: Included,
        *,
        legal_name: str | None,
        location_filter: LocationFilter | None,
        website: str | None,
        ria: bool | None,
        internal_organization: bool | None,
        predicates: tuple[CustomFieldMatch, ...],
    ) -> tuple[tuple[tuple[int, SearchOrganizationRowResponse], ...], int]:
        """`(index, row)` for each match in `resources`, and how many were unreadable."""
        selected: list[tuple[int, SearchOrganizationRowResponse]] = []
        dropped = 0
        for index, resource in enumerate(resources):
            try:
                row = self._row(
                    resource,
                    included,
                    legal_name=legal_name,
                    location_filter=location_filter,
                    website=website,
                    ria=ria,
                    internal_organization=internal_organization,
                    predicates=predicates,
                )
            except ValidationError as exc:
                dropped += 1
                logger.warning(
                    "org_people.search.record.unreadable",
                    extra={"organization_id": resource.id},
                    exc_info=exc,
                )
                continue
            if row is not None:
                selected.append((index, row))
        return tuple(selected), dropped

    def _row(
        self,
        resource: OrganizationResource,
        included: Included,
        *,
        legal_name: str | None,
        location_filter: LocationFilter | None,
        website: str | None,
        ria: bool | None,
        internal_organization: bool | None,
        predicates: tuple[CustomFieldMatch, ...],
    ) -> SearchOrganizationRowResponse | None:
        attributes = resource.attributes
        if not self._matches_text(attributes.legal_name, legal_name):
            return None
        locations = party_locations(
            attributes,
            included.related(resource, "contactLocations", schema=LocationResource),
        )
        if location_filter is not None and not matches_location(locations, location_filter):
            return None
        if not self._matches_text(attributes.website, website):
            return None
        if ria is not None and attributes.ria is not ria:
            return None
        if (
            internal_organization is not None
            and attributes.internal_organization is not internal_organization
        ):
            return None
        if not satisfies_every(attributes.regular_custom_field_values, predicates):
            return None
        return SearchOrganizationRowResponse(
            id=resource.id,
            name=attributes.name,
            legal_name=attributes.legal_name,
            email=attributes.email,
            city=attributes.city,
            country=attributes.country,
            state=attributes.state,
            postal_code=attributes.postal_code,
            street_address=attributes.street_address,
            location_title=attributes.location_title,
            website=attributes.website,
            locations=tuple(
                ContactLocationResponse.model_validate(
                    location.model_dump(exclude={"country_code"})
                )
                for location in locations
            )
            or None,
            other_id=attributes.other_id,
            matching_domains=attributes.matching_domains,
            ria=attributes.ria,
            internal_organization=attributes.internal_organization,
            custom_field_values=stored_custom_field_values(attributes.regular_custom_field_values)
            or None,
        )

    def _project(
        self, selected: tuple[SearchOrganizationRowResponse, ...], *, fields: frozenset[str]
    ) -> tuple[SearchOrganizationRowResponse, ...]:
        return tuple(
            row.project(
                fields=fields,
                url=(
                    self._build_entity_link_util.canonical_url(
                        target=OrganizationLinkTarget(party_id=row.id)
                    )
                    if "url" in fields
                    else None
                ),
            )
            for row in selected
        )

    def _has_in_memory_predicate(
        self,
        *,
        legal_name: str | None,
        location_filter: LocationFilter | None,
        website: str | None,
        ria: bool | None,
        internal_organization: bool | None,
        predicates: tuple[CustomFieldMatch, ...],
    ) -> bool:
        return any(
            value is not None
            for value in (
                legal_name,
                location_filter,
                website,
                ria,
                internal_organization,
            )
        ) or bool(predicates)

    @staticmethod
    def _text(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @staticmethod
    def _matches_text(haystack: str | None, needle: str | None) -> bool:
        if needle is None:
            return True
        return needle.casefold() in (haystack or "").casefold()
