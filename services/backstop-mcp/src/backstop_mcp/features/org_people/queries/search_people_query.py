"""Firm-wide `GET /people`: server-side name, email, otherId and domain filters, the rest in memory.

Locations come from `include=contactLocations` (only exact `city`/`address` filters exist);
employment links are fetched only when asked for. `sort=name` is a 500 here, so rows are
sorted by name in memory.
"""

import asyncio
import logging
from collections.abc import Sequence

from opentelemetry import trace
from pydantic import ValidationError

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopClient,
    Included,
    PageResult,
)
from backstop_mcp.features.collection_scan import scan_coverage
from backstop_mcp.features.custom_fields import (
    CustomFieldMatch,
    normalize_matches,
    satisfies_every,
    stored_custom_field_values,
)
from backstop_mcp.features.data_hygiene import (
    EmploymentIndexFactory,
    EmploymentLinkResponse,
    EntityRelationshipAttributes,
    EntityRelationshipInclude,
    EntityRelationshipRef,
    RelationshipTypeAttributes,
)
from backstop_mcp.features.includes import ContactLocationResponse
from backstop_mcp.features.org_people.api_responses import LocationResource, PersonResource
from backstop_mcp.features.org_people.inputs import LocationFilter
from backstop_mcp.features.org_people.responses import (
    SearchPeopleResolvedResponse,
    SearchPersonRowResponse,
)
from backstop_mcp.features.org_people.utils import (
    location_filter_params,
    matches_location,
    party_locations,
)
from backstop_mcp.features.ui_links import BuildEntityLinkUtil, PersonLinkTarget

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

# Above the people collection this was sized against (about twenty thousand). A larger
# collection stops here and says so in `coverage`.
MAX_PEOPLE_SCAN_RECORDS = 30_000

_PAGE_SIZE = 500
_EMAIL_FIELDS: tuple[str, ...] = ("email", "email2", "email3")


class SearchPeopleQuery:
    """Walk `GET /people` and keep rows that match every predicate."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        employment_index_factory: EmploymentIndexFactory,
        build_entity_link_util: BuildEntityLinkUtil,
    ) -> None:
        self._client: BackstopClient = client
        self._employment_index_factory: EmploymentIndexFactory = employment_index_factory
        self._build_entity_link_util: BuildEntityLinkUtil = build_entity_link_util

    async def run(
        self,
        *,
        name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        other_id: str | None = None,
        email_domain: str | None = None,
        first_name: str | None = None,
        job_title: str | None = None,
        company_name: str | None = None,
        department: str | None = None,
        location_filter: LocationFilter | None = None,
        website: str | None = None,
        custom_fields: Sequence[CustomFieldMatch] = (),
        min_current_organizations: int | None = None,
        exclude_custom_fields: bool = False,
        fields: frozenset[str],
    ) -> SearchPeopleResolvedResponse:
        """Read the server-filtered collection, then apply predicates Backstop rejects."""
        name = self._text(name)
        last_name = self._text(last_name)
        email = self._text(email)
        other_id = self._text(other_id)
        email_domain = self._text(email_domain)
        first_name = self._text(first_name)
        job_title = self._text(job_title)
        company_name = self._text(company_name)
        department = self._text(department)
        website = self._text(website)
        predicates = normalize_matches(custom_fields)
        should_filter_in_memory = self._has_in_memory_predicate(
            first_name=first_name,
            job_title=job_title,
            company_name=company_name,
            department=department,
            location_filter=location_filter,
            website=website,
            predicates=predicates,
            min_current_organizations=min_current_organizations,
        )
        with_employments = min_current_organizations is not None or "employments" in fields
        with _tracer.start_as_current_span("org_people.query.search_people") as span:
            span.set_attribute("memory", should_filter_in_memory)
            resources, included, total_count, ceiling_clamped = await self._read(
                name=name,
                last_name=last_name,
                email=email,
                other_id=other_id,
                email_domain=email_domain,
                exclude_custom_fields=exclude_custom_fields,
                location_filter=location_filter,
                with_employments=with_employments,
            )
            selected, dropped = self._select(
                resources,
                included,
                employments=self._employments_by_person(included) if with_employments else None,
                min_current_organizations=min_current_organizations,
                first_name=first_name,
                job_title=job_title,
                company_name=company_name,
                department=department,
                location_filter=location_filter,
                website=website,
                predicates=predicates,
            )
            selected = tuple(sorted(selected, key=self._name_order))
            span.set_attribute("rows_scanned", len(resources))
            span.set_attribute("matched", len(selected))
            logger.info(
                "org_people.search_people.fetched",
                extra={
                    "memory": should_filter_in_memory,
                    "rows_scanned": len(resources),
                    "matched": len(selected),
                    "dropped": dropped,
                    "total_count": total_count,
                },
            )
            projected = fields | {"id"}
            if min_current_organizations is not None:
                projected = projected | {"employments"}
            if not exclude_custom_fields:
                projected = projected | {"custom_field_values"}
            return self._to_response(
                selected,
                fields=projected,
                rows_scanned=len(resources),
                rows_dropped=dropped,
                total_count=total_count,
                ceiling_clamped=ceiling_clamped,
            )

    async def _read(
        self,
        *,
        name: str | None,
        last_name: str | None,
        email: str | None,
        other_id: str | None,
        email_domain: str | None,
        exclude_custom_fields: bool,
        location_filter: LocationFilter | None,
        with_employments: bool,
    ) -> tuple[tuple[PersonResource, ...], Included, int | None, bool]:
        params = {
            **self._query_params(
                name=name,
                last_name=last_name,
                other_id=other_id,
                email_domain=email_domain,
                exclude_custom_fields=exclude_custom_fields,
                with_employments=with_employments,
            ),
            **location_filter_params(location_filter),
        }
        if email is None:
            page = await self._fetch(params)
            return tuple(page.items), Included(page.included), page.total_count, page.truncated
        pages = await asyncio.gather(
            *(self._fetch({**params, f"filter[{field}][eq]": email}) for field in _EMAIL_FIELDS)
        )
        return self._merge(pages)

    async def _fetch(self, params: dict[str, object]) -> PageResult[PersonResource]:
        return await self._client.paginate(
            "/people",
            schema=PersonResource,
            params=params,
            max_records=MAX_PEOPLE_SCAN_RECORDS,
            page_size=_PAGE_SIZE,
            parallel=True,
        )

    def _query_params(
        self,
        *,
        name: str | None,
        last_name: str | None,
        other_id: str | None,
        email_domain: str | None,
        exclude_custom_fields: bool,
        with_employments: bool,
    ) -> dict[str, object]:
        wire_fields = [
            "name",
            "firstName",
            "lastName",
            "email",
            "email2",
            "email3",
            "jobTitle",
            "companyName",
            "department",
            "city",
            "country",
            "state",
            "postalCode",
            "streetAddress",
            "locationTitle",
            "website",
            "otherId",
        ]
        if not exclude_custom_fields:
            wire_fields.append("regularCustomFieldValues")
        includes = ["contactLocations"]
        if with_employments:
            includes.append(EntityRelationshipInclude.for_employment())
        params: dict[str, object] = {
            "sort": "id",
            "include": ",".join(includes),
            "fields[people]": ",".join(wire_fields),
        }
        if name is not None:
            params["filter[name][eq]"] = name
        if last_name is not None:
            params["filter[lastName][like]"] = last_name
        if other_id is not None:
            params["filter[otherId][eq]"] = other_id
        if email_domain is not None:
            params["filter[emailDomains][eq]"] = email_domain
        return params

    def _merge(
        self, pages: Sequence[PageResult[PersonResource]]
    ) -> tuple[tuple[PersonResource, ...], Included, int | None, bool]:
        by_id: dict[str, PersonResource] = {}
        for page in pages:
            for resource in page.items:
                by_id.setdefault(resource.id, resource)
        return (
            tuple(by_id.values()),
            Included([item for page in pages for item in page.included]),
            self._visible_count(pages),
            any(page.truncated for page in pages),
        )

    def _employments_by_person(
        self, included: Included
    ) -> dict[str, tuple[EmploymentLinkResponse, ...]]:
        """Every walked person's employment links, from one index over the whole walk."""
        index = self._employment_index_factory.index(
            relationships=included.by_type(
                EntityRelationshipRef.RELATIONSHIPS_RESOURCE,
                schema=BackstopApiResource[EntityRelationshipAttributes],
            ),
            relationship_types=included.by_type(
                EntityRelationshipRef.TYPES_RESOURCE,
                schema=BackstopApiResource[RelationshipTypeAttributes],
            ),
        )
        by_person: dict[str, list[EmploymentLinkResponse]] = {}
        for link in index.links():
            by_person.setdefault(link.person_id, []).append(link)
        return {person_id: tuple(links) for person_id, links in by_person.items()}

    def _select(
        self,
        resources: Sequence[PersonResource],
        included: Included,
        *,
        employments: dict[str, tuple[EmploymentLinkResponse, ...]] | None,
        min_current_organizations: int | None,
        first_name: str | None,
        job_title: str | None,
        company_name: str | None,
        department: str | None,
        location_filter: LocationFilter | None,
        website: str | None,
        predicates: tuple[CustomFieldMatch, ...],
    ) -> tuple[tuple[SearchPersonRowResponse, ...], int]:
        selected: list[SearchPersonRowResponse] = []
        dropped = 0
        for resource in resources:
            try:
                row = self._row(
                    resource,
                    included,
                    employments=None if employments is None else employments.get(resource.id, ()),
                    min_current_organizations=min_current_organizations,
                    first_name=first_name,
                    job_title=job_title,
                    company_name=company_name,
                    department=department,
                    location_filter=location_filter,
                    website=website,
                    predicates=predicates,
                )
            except ValidationError as exc:
                dropped += 1
                logger.warning(
                    "org_people.search_people.record.unreadable",
                    extra={"person_id": resource.id},
                    exc_info=exc,
                )
                continue
            if row is not None:
                selected.append(row)
        return tuple(selected), dropped

    def _row(
        self,
        resource: PersonResource,
        included: Included,
        *,
        employments: tuple[EmploymentLinkResponse, ...] | None,
        min_current_organizations: int | None,
        first_name: str | None,
        job_title: str | None,
        company_name: str | None,
        department: str | None,
        location_filter: LocationFilter | None,
        website: str | None,
        predicates: tuple[CustomFieldMatch, ...],
    ) -> SearchPersonRowResponse | None:
        attributes = resource.attributes
        if not self._matches_text(attributes.first_name, first_name):
            return None
        if not self._matches_text(attributes.job_title, job_title):
            return None
        if not self._matches_text(attributes.company_name, company_name):
            return None
        if not self._matches_text(attributes.department, department):
            return None
        locations = party_locations(
            attributes,
            included.related(resource, "contactLocations", schema=LocationResource),
        )
        if location_filter is not None and not matches_location(locations, location_filter):
            return None
        if not self._matches_text(attributes.website, website):
            return None
        if not satisfies_every(attributes.regular_custom_field_values, predicates):
            return None
        if min_current_organizations is not None:
            current = {
                link.organization_id for link in employments or () if link.status == "current"
            }
            if len(current) < min_current_organizations:
                return None
        return SearchPersonRowResponse(
            id=resource.id,
            name=attributes.name,
            first_name=attributes.first_name,
            last_name=attributes.last_name,
            email=attributes.email,
            email2=attributes.email2,
            email3=attributes.email3,
            job_title=attributes.job_title,
            company_name=attributes.company_name,
            department=attributes.department,
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
            custom_field_values=stored_custom_field_values(attributes.regular_custom_field_values)
            or None,
            employments=employments or None,
        )

    def _to_response(
        self,
        selected: tuple[SearchPersonRowResponse, ...],
        *,
        fields: frozenset[str],
        rows_scanned: int,
        rows_dropped: int,
        total_count: int | None,
        ceiling_clamped: bool,
    ) -> SearchPeopleResolvedResponse:
        coverage = scan_coverage(
            rows_scanned=rows_scanned,
            visible_count=total_count,
            rows_dropped=rows_dropped,
            ceiling=MAX_PEOPLE_SCAN_RECORDS,
            ceiling_clamped=ceiling_clamped,
            # One `paginate` call, or three email lookups: a failed page raises.
            partial_due_to_error=False,
        )
        rows = tuple(
            row.project(
                fields=fields,
                url=(
                    self._build_entity_link_util.canonical_url(
                        target=PersonLinkTarget(party_id=row.id)
                    )
                    if "url" in fields
                    else None
                ),
            )
            for row in selected
        )
        return SearchPeopleResolvedResponse(coverage=coverage, rows=rows)

    def _has_in_memory_predicate(
        self,
        *,
        first_name: str | None,
        job_title: str | None,
        company_name: str | None,
        department: str | None,
        location_filter: LocationFilter | None,
        website: str | None,
        predicates: tuple[CustomFieldMatch, ...],
        min_current_organizations: int | None,
    ) -> bool:
        return (
            min_current_organizations is not None
            or any(
                value is not None
                for value in (
                    first_name,
                    job_title,
                    company_name,
                    department,
                    location_filter,
                    website,
                )
            )
            or bool(predicates)
        )

    @staticmethod
    def _visible_count(pages: Sequence[PageResult[PersonResource]]) -> int | None:
        total = 0
        for page in pages:
            if page.total_count is None:
                return None
            total += page.total_count
        return total

    @staticmethod
    def _text(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @staticmethod
    def _name_order(row: SearchPersonRowResponse) -> str:
        return (row.name or "").casefold()

    @staticmethod
    def _matches_text(haystack: str | None, needle: str | None) -> bool:
        if needle is None:
            return True
        return needle.casefold() in (haystack or "").casefold()
