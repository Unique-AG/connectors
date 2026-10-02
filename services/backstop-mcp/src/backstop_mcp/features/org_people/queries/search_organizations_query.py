"""Firm-wide `GET /organizations`: server filters where Backstop accepts them, then in memory.

`filter[name][like]`, `filter[email][eq]`, `filter[otherId][eq]`, and
`filter[matchingDomains][eq]` change `totalResourceCount` on this API. `filter[city]`,
`filter[legalName]`, `filter[website]`, `filter[ria]`, `filter[internalOrganization]`,
`filter[email2]`, and any custom-field field name are `400 Invalid filter field`.
`filter[regularCustomFieldValues][eq]` is recognized and then rejected: Backstop cannot
convert a query-string value into `RegularCustomFieldValueDto`. Those predicates run
after the fetch. `filter[email][eq]` is the primary email only.

A custom-field-only call reads the collection. Large tenants have thousands of
organizations; a sparse page carrying `regularCustomFieldValues` takes seconds, and the
per-user gate allows five concurrent requests, so the walk requests later pages in
parallel. Every match is returned; the scan ceiling is the only limit.
"""

import logging
from collections.abc import Sequence

from opentelemetry import trace
from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.collection_scan import scan_coverage
from backstop_mcp.features.custom_fields import (
    CustomFieldMatch,
    normalize_matches,
    satisfies_every,
    stored_custom_field_values,
)
from backstop_mcp.features.org_people.api_responses import OrganizationResource
from backstop_mcp.features.org_people.responses import (
    SearchOrganizationRowResponse,
    SearchOrganizationsResolvedResponse,
)
from backstop_mcp.features.ui_links import BuildEntityLinkUtil, OrganizationLinkTarget

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

# Scan ceiling. A larger collection stops here and says so in `coverage` rather than
# reading without a bound.
MAX_ORGANIZATION_SCAN_RECORDS = 10_000

_PAGE_SIZE = 500


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
        city: str | None = None,
        country: str | None = None,
        state: str | None = None,
        website: str | None = None,
        ria: bool | None = None,
        internal_organization: bool | None = None,
        custom_fields: Sequence[CustomFieldMatch] = (),
        exclude_custom_fields: bool = False,
        fields: frozenset[str],
    ) -> SearchOrganizationsResolvedResponse:
        """Read the server-filtered collection, then apply predicates Backstop rejects."""
        name = self._text(name)
        email = self._text(email)
        other_id = self._text(other_id)
        matching_domain = self._text(matching_domain)
        legal_name = self._text(legal_name)
        city = self._text(city)
        country = self._text(country)
        state = self._text(state)
        website = self._text(website)
        predicates = normalize_matches(custom_fields)
        should_filter_in_memory = self._has_in_memory_predicate(
            legal_name=legal_name,
            city=city,
            country=country,
            state=state,
            website=website,
            ria=ria,
            internal_organization=internal_organization,
            predicates=predicates,
        )
        with _tracer.start_as_current_span("org_people.query.search_organizations") as span:
            span.set_attribute("memory", should_filter_in_memory)
            pages = await self._client.paginate(
                "/organizations",
                schema=OrganizationResource,
                params=self._query_params(
                    name=name,
                    email=email,
                    other_id=other_id,
                    matching_domain=matching_domain,
                    exclude_custom_fields=exclude_custom_fields,
                ),
                max_records=MAX_ORGANIZATION_SCAN_RECORDS,
                page_size=_PAGE_SIZE,
                parallel=True,
            )
            selected, dropped = self._select(
                pages.items,
                legal_name=legal_name,
                city=city,
                country=country,
                state=state,
                website=website,
                ria=ria,
                internal_organization=internal_organization,
                predicates=predicates,
            )
            if should_filter_in_memory:
                selected = tuple(sorted(selected, key=self._name_order))
            span.set_attribute("rows_scanned", len(pages.items))
            span.set_attribute("matched", len(selected))
            logger.info(
                "org_people.search.fetched",
                extra={
                    "memory": should_filter_in_memory,
                    "rows_scanned": len(pages.items),
                    "matched": len(selected),
                    "dropped": dropped,
                    "total_count": pages.total_count,
                },
            )
            projected = fields | {"id"}
            if not exclude_custom_fields:
                projected = projected | {"custom_field_values"}
            return self._to_response(
                selected,
                fields=projected,
                rows_scanned=len(pages.items),
                rows_dropped=dropped,
                total_count=pages.total_count,
                ceiling_clamped=pages.truncated,
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
            "website",
            "otherId",
            "matchingDomains",
            "ria",
            "internalOrganization",
        ]
        if not exclude_custom_fields:
            wire_fields.append("regularCustomFieldValues")
        params: dict[str, object] = {
            "sort": "name",
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
        *,
        legal_name: str | None,
        city: str | None,
        country: str | None,
        state: str | None,
        website: str | None,
        ria: bool | None,
        internal_organization: bool | None,
        predicates: tuple[CustomFieldMatch, ...],
    ) -> tuple[tuple[SearchOrganizationRowResponse, ...], int]:
        selected: list[SearchOrganizationRowResponse] = []
        dropped = 0
        for resource in resources:
            try:
                row = self._row(
                    resource,
                    legal_name=legal_name,
                    city=city,
                    country=country,
                    state=state,
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
                selected.append(row)
        return tuple(selected), dropped

    def _row(
        self,
        resource: OrganizationResource,
        *,
        legal_name: str | None,
        city: str | None,
        country: str | None,
        state: str | None,
        website: str | None,
        ria: bool | None,
        internal_organization: bool | None,
        predicates: tuple[CustomFieldMatch, ...],
    ) -> SearchOrganizationRowResponse | None:
        attributes = resource.attributes
        if not self._matches_text(attributes.legal_name, legal_name):
            return None
        if not self._matches_text(attributes.city, city):
            return None
        if not self._matches_text(attributes.country, country):
            return None
        if not self._matches_text(attributes.state, state):
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
            website=attributes.website,
            other_id=attributes.other_id,
            matching_domains=attributes.matching_domains,
            ria=attributes.ria,
            internal_organization=attributes.internal_organization,
            custom_field_values=stored_custom_field_values(attributes.regular_custom_field_values)
            or None,
        )

    def _to_response(
        self,
        selected: tuple[SearchOrganizationRowResponse, ...],
        *,
        fields: frozenset[str],
        rows_scanned: int,
        rows_dropped: int,
        total_count: int | None,
        ceiling_clamped: bool,
    ) -> SearchOrganizationsResolvedResponse:
        coverage = scan_coverage(
            rows_scanned=rows_scanned,
            visible_count=total_count,
            rows_dropped=rows_dropped,
            ceiling=MAX_ORGANIZATION_SCAN_RECORDS,
            ceiling_clamped=ceiling_clamped,
            # One `paginate` call: a failed page raises rather than returning a short list.
            partial_due_to_error=False,
        )
        rows = tuple(
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
        return SearchOrganizationsResolvedResponse(coverage=coverage, rows=rows)

    def _has_in_memory_predicate(
        self,
        *,
        legal_name: str | None,
        city: str | None,
        country: str | None,
        state: str | None,
        website: str | None,
        ria: bool | None,
        internal_organization: bool | None,
        predicates: tuple[CustomFieldMatch, ...],
    ) -> bool:
        return any(
            value is not None
            for value in (
                legal_name,
                city,
                country,
                state,
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
    def _name_order(row: SearchOrganizationRowResponse) -> str:
        return (row.name or "").casefold()

    @staticmethod
    def _matches_text(haystack: str | None, needle: str | None) -> bool:
        if needle is None:
            return True
        return needle.casefold() in (haystack or "").casefold()
