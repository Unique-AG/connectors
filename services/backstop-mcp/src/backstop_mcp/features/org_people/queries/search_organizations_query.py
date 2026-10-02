"""Firm-wide `GET /organizations`: server filters where Backstop accepts them, then in memory.

`filter[name][like]`, `filter[email][eq]`, `filter[otherId][eq]`, and
`filter[matchingDomains][eq]` change `totalResourceCount` on this API. `filter[city]`,
`filter[legalName]`, `filter[website]`, `filter[ria]`, `filter[internalOrganization]`,
`filter[email2]`, and any custom-field field name are `400 Invalid filter field`.
`filter[regularCustomFieldValues][eq]` is recognized and then rejected: Backstop cannot
convert a query-string value into `RegularCustomFieldValueDto`. Those predicates run
after the fetch. `filter[email][eq]` is the primary email only.

A custom-field-only call reads the collection. On a client-obtained tenant that was
5,129 organizations: a sparse page of 500 carrying `regularCustomFieldValues` took a
few seconds, and the per-user gate allows five concurrent requests, so the in-memory
walk requests later pages in parallel instead of chaining all eleven. `parallel` stays
off when every predicate is a server filter — that walk stops at `max_rows`.
"""

import logging
from collections.abc import Sequence
from typing import NamedTuple, cast

from opentelemetry import trace
from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.collection_scan import scan_coverage
from backstop_mcp.features.org_people.api_responses import (
    OrganizationAttributes,
    OrganizationResource,
)
from backstop_mcp.features.org_people.responses import (
    MatchedCustomFieldResponse,
    OrganizationCustomFieldColumnResponse,
    SearchOrganizationRowResponse,
    SearchOrganizationsResolvedResponse,
)
from backstop_mcp.features.ui_links import BuildEntityLinkUtil, OrganizationLinkTarget

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

# Headroom over the 5,129 organizations measured on a client-obtained tenant. A larger
# collection stops here and says so in `coverage` rather than reading without a bound.
MAX_ORGANIZATION_SCAN_RECORDS = 10_000

_PAGE_SIZE = 500


class OrganizationCustomFieldMatch(NamedTuple):
    """One custom-field predicate: definition id, then the stored values that satisfy it (OR)."""

    definition_id: str
    values: tuple[str, ...]


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
        custom_fields: Sequence[OrganizationCustomFieldMatch] = (),
        custom_field_columns: Sequence[str] = (),
        max_rows: int,
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
        predicates = self._predicates(custom_fields)
        columns = tuple(
            dict.fromkeys(item.strip() for item in custom_field_columns if item.strip())
        )
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
                    include_custom_fields=bool(predicates) or bool(columns),
                ),
                max_records=MAX_ORGANIZATION_SCAN_RECORDS if should_filter_in_memory else max_rows,
                page_size=_PAGE_SIZE if should_filter_in_memory else min(max_rows, _PAGE_SIZE),
                parallel=should_filter_in_memory,
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
                columns=columns,
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
            if predicates:
                projected = projected | {"custom_field_values"}
            if columns:
                projected = projected | {"custom_field_columns"}
            return self._to_response(
                selected,
                fields=projected,
                max_rows=max_rows,
                rows_scanned=len(pages.items),
                rows_dropped=dropped,
                total_count=pages.total_count,
                truncated_by_row_cap=self._row_cap(
                    kept=len(selected),
                    total_count=pages.total_count,
                    max_rows=max_rows,
                    memory=should_filter_in_memory,
                    fetched=len(pages.items),
                ),
                ceiling_clamped=should_filter_in_memory and pages.truncated,
            )

    def _query_params(
        self,
        *,
        name: str | None,
        email: str | None,
        other_id: str | None,
        matching_domain: str | None,
        include_custom_fields: bool,
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
        if include_custom_fields:
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
        predicates: tuple[OrganizationCustomFieldMatch, ...],
        columns: tuple[str, ...],
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
                    columns=columns,
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
        predicates: tuple[OrganizationCustomFieldMatch, ...],
        columns: tuple[str, ...],
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
        matched = self._matched_custom_fields(attributes, predicates)
        if matched is None:
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
            custom_field_values=matched or None,
            custom_field_columns=self._column_values(attributes, columns) or None,
        )

    def _to_response(
        self,
        selected: tuple[SearchOrganizationRowResponse, ...],
        *,
        fields: frozenset[str],
        max_rows: int,
        rows_scanned: int,
        rows_dropped: int,
        total_count: int | None,
        truncated_by_row_cap: bool,
        ceiling_clamped: bool,
    ) -> SearchOrganizationsResolvedResponse:
        coverage = scan_coverage(
            rows_scanned=rows_scanned,
            visible_count=total_count,
            rows_dropped=rows_dropped,
            ceiling=MAX_ORGANIZATION_SCAN_RECORDS,
            ceiling_clamped=ceiling_clamped,
            truncated_by_row_cap=truncated_by_row_cap,
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
            for row in selected[:max_rows]
        )
        return SearchOrganizationsResolvedResponse(coverage=coverage, rows=rows)

    def _predicates(
        self, custom_fields: Sequence[OrganizationCustomFieldMatch]
    ) -> tuple[OrganizationCustomFieldMatch, ...]:
        normalized = (
            OrganizationCustomFieldMatch(
                definition_id=predicate.definition_id.strip(),
                values=tuple(value.strip() for value in predicate.values if value.strip()),
            )
            for predicate in custom_fields
        )
        return tuple(
            predicate for predicate in normalized if predicate.definition_id and predicate.values
        )

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
        predicates: tuple[OrganizationCustomFieldMatch, ...],
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

    def _matched_custom_fields(
        self,
        attributes: OrganizationAttributes,
        predicates: tuple[OrganizationCustomFieldMatch, ...],
    ) -> tuple[MatchedCustomFieldResponse, ...] | None:
        """Values that satisfy every predicate, or None when one predicate misses.

        An empty predicate list matches every organization and publishes no values.
        """
        if not predicates:
            return ()
        matched: list[MatchedCustomFieldResponse] = []
        for predicate in predicates:
            needles = tuple(value.casefold() for value in predicate.values)
            hits: list[MatchedCustomFieldResponse] = []
            for value in attributes.regular_custom_field_values:
                if value.definition_id != predicate.definition_id:
                    continue
                text = next(
                    (
                        found
                        for needle in needles
                        if (found := self._matching_text(value.value, needle)) is not None
                    ),
                    None,
                )
                if text is None:
                    continue
                hits.append(
                    MatchedCustomFieldResponse(
                        definition_id=predicate.definition_id,
                        name=value.name,
                        value=text,
                    )
                )
            if not hits:
                return None
            matched.extend(hits)
        return tuple(matched)

    def _column_values(
        self, attributes: OrganizationAttributes, columns: tuple[str, ...]
    ) -> tuple[OrganizationCustomFieldColumnResponse, ...]:
        """Stored values for the requested definitions, in request order; unset ones are absent."""
        by_definition = {
            value.definition_id: value for value in attributes.regular_custom_field_values
        }
        published: list[OrganizationCustomFieldColumnResponse] = []
        for definition_id in columns:
            value = by_definition.get(definition_id)
            if value is None:
                continue
            text = self._display_text(value.value)
            if text is None:
                continue
            published.append(
                OrganizationCustomFieldColumnResponse(
                    definition_id=definition_id, name=value.name, value=text
                )
            )
        return tuple(published)

    def _display_text(self, stored: object) -> str | None:
        if isinstance(stored, bool):
            return "true" if stored else "false"
        if isinstance(stored, str):
            return stored.strip() or None
        if isinstance(stored, int | float):
            return str(stored)
        if isinstance(stored, list):
            parts = [
                text
                for item in cast("list[object]", stored)
                if (text := self._display_text(item)) is not None
            ]
            return "; ".join(parts) or None
        return None

    def _matching_text(self, stored: object, needle: str) -> str | None:
        if isinstance(stored, bool):
            text = "true" if stored else "false"
            return text if text == needle else None
        if isinstance(stored, str):
            return stored if stored.casefold() == needle else None
        if isinstance(stored, int | float):
            text = str(stored)
            return text if text.casefold() == needle else None
        if isinstance(stored, list):
            for item in cast("list[object]", stored):
                text = self._matching_text(item, needle)
                if text is not None:
                    return text
        return None

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
    def _row_cap(
        *,
        kept: int,
        total_count: int | None,
        max_rows: int,
        memory: bool,
        fetched: int,
    ) -> bool:
        if memory:
            return kept > max_rows
        if total_count is not None:
            return total_count > max_rows
        return fetched >= max_rows

    @staticmethod
    def _matches_text(haystack: str | None, needle: str | None) -> bool:
        if needle is None:
            return True
        return needle.casefold() in (haystack or "").casefold()
