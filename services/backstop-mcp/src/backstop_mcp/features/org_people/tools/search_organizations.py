"""`search_organizations`: firm-wide organization filter.

`name`, `email`, `other_id`, and `matching_domain` are sent to Backstop.
`legal_name`, `city`, `country`, `state`, `website`, `ria`, `internal_organization`,
and custom fields are applied after the walk: those filter fields are 400 on
`GET /organizations`. A custom-field-only call reads the collection.
"""

import logging
from collections.abc import Sequence
from typing import Annotated, Literal

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from opentelemetry import trace
from pydantic import BaseModel, Field

from backstop_mcp.features.org_people import (
    MAX_ORGANIZATION_SCAN_RECORDS,
    OrganizationCustomFieldMatch,
    SearchOrganizationsQuery,
    SearchOrganizationsResolvedResponse,
)
from backstop_mcp.features.org_people.dependencies import get_search_organizations_query_factory
from backstop_mcp.models import CoercedId, NonEmptyStr, published_output_schema

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_DEFAULT_MAX_ROWS = 100
_MAX_ROWS = 1_000

SearchOrganizationField = Literal[
    "id",
    "url",
    "name",
    "legal_name",
    "email",
    "city",
    "country",
    "state",
    "website",
    "other_id",
    "matching_domains",
    "ria",
    "internal_organization",
]
_DEFAULT_FIELDS: frozenset[str] = frozenset(
    {"id", "name", "legal_name", "email", "city", "country"}
)


class OrganizationCustomFieldFilter(BaseModel):
    """One custom-field predicate. Several predicates AND together."""

    definition_id: CoercedId = Field(
        description=(
            "Custom-field definition id from list_custom_fields. Not the field label: "
            "two definitions can share a name, and a label sent as a filter is 400."
        )
    )
    values: list[NonEmptyStr] = Field(
        min_length=1,
        description=(
            "Stored values that satisfy this predicate, OR. Each is compared whole and "
            "case-insensitively against the select options list_custom_fields returns — "
            "pass every option that counts (e.g. every status that means 'in dialogue'), "
            "not a substring. A list value matches when any element equals one of these. "
            "A missing value does not match — this filter cannot mean 'the field is empty'."
        ),
    )


def _predicates(
    custom_fields: Sequence[OrganizationCustomFieldFilter] | None,
) -> tuple[OrganizationCustomFieldMatch, ...]:
    if not custom_fields:
        return ()
    return tuple(
        OrganizationCustomFieldMatch(definition_id=item.definition_id, values=tuple(item.values))
        for item in custom_fields
    )


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(SearchOrganizationsResolvedResponse),
)
async def search_organizations(
    name: Annotated[
        str | None,
        Field(
            description=(
                "Substring of the organization name. Sent as filter[name][like]. "
                "Not a prefix-only quick search."
            )
        ),
    ] = None,
    email: Annotated[
        str | None,
        Field(
            description=(
                "Primary email, exact. Sent as filter[email][eq]. email2 and email3 "
                "are not filterable on this collection."
            )
        ),
    ] = None,
    other_id: Annotated[
        str | None,
        Field(description="Backstop otherId, exact. Sent as filter[otherId][eq]."),
    ] = None,
    matching_domain: Annotated[
        str | None,
        Field(description=("One email domain, exact. Sent as filter[matchingDomains][eq].")),
    ] = None,
    legal_name: Annotated[
        str | None,
        Field(
            description=(
                "Substring of the legal name. Applied after the walk — filter[legalName] is 400."
            )
        ),
    ] = None,
    city: Annotated[
        str | None,
        Field(description=("Substring of the city. Applied after the walk — filter[city] is 400.")),
    ] = None,
    country: Annotated[
        str | None,
        Field(
            description=(
                "Substring of the country as stored, which is the full name ('United Arab "
                "Emirates', 'United States of America') — an abbreviation like 'UAE' or "
                "'USA' matches nothing. Applied after the walk — filter[country] is 400."
            )
        ),
    ] = None,
    state: Annotated[
        str | None,
        Field(
            description=(
                "Substring of the state or region. Applied after the walk — "
                "filter[state] is not a collection filter."
            )
        ),
    ] = None,
    website: Annotated[
        str | None,
        Field(
            description=(
                "Substring of the website. Applied after the walk — filter[website] is 400."
            )
        ),
    ] = None,
    ria: Annotated[
        bool | None,
        Field(description=("Exact RIA flag. Applied after the walk — filter[ria] is 400.")),
    ] = None,
    internal_organization: Annotated[
        bool | None,
        Field(
            description=(
                "Exact internal-organization flag. Applied after the walk — "
                "filter[internalOrganization] is 400."
            )
        ),
    ] = None,
    custom_fields: Annotated[
        list[OrganizationCustomFieldFilter] | None,
        Field(
            description=(
                "Custom-field predicates, AND. Each is a definition id from "
                "list_custom_fields plus the stored value. Applied after the walk: "
                "a custom-field name, a definition id used as the filter field, and "
                "filter[regularCustomFieldValues] are all 400. A call that sets only "
                "these reads the collection (up to "
                f"{MAX_ORGANIZATION_SCAN_RECORDS} rows) and says so in `coverage`."
            )
        ),
    ] = None,
    custom_field_columns: Annotated[
        list[CoercedId] | None,
        Field(
            description=(
                "Custom-field definition ids from list_custom_fields whose values to publish "
                "on every row as `custom_field_columns` — the fields a table is grouped or "
                "labelled by (e.g. Grade, Investor Type). Does not filter. One walk answers "
                "'grouped by X and Y'; never call get_organization per row for these."
            )
        ),
    ] = None,
    max_rows: Annotated[
        int,
        Field(
            ge=1,
            le=_MAX_ROWS,
            description=(
                "Row-body cap. Does not limit a walk that has an in-memory predicate: "
                f"that walk reads up to {MAX_ORGANIZATION_SCAN_RECORDS} rows. When every "
                "predicate is a server filter, the read stops at this cap."
            ),
        ),
    ] = _DEFAULT_MAX_ROWS,
    fields: Annotated[
        list[SearchOrganizationField] | None,
        Field(
            description=(
                "Sparse row fields. Defaults to id, name, legal_name, email, city, "
                "country. `id` is always included. Select `url` when the answer will "
                "link to the organization — it is off by default. Matching custom-field "
                "values are included automatically when `custom_fields` is set, and "
                "requested columns when `custom_field_columns` is set."
            )
        ),
    ] = None,
    search_organizations_query: SearchOrganizationsQuery = Depends(
        get_search_organizations_query_factory
    ),
) -> SearchOrganizationsResolvedResponse:
    """Filter organizations across the firm.

    `name`, `email`, `other_id`, and `matching_domain` are sent to Backstop and narrow
    the read. `legal_name`, `city`, `country`, `state`, `website`, `ria`,
    `internal_organization`, and `custom_fields` are applied after that walk. A call
    with only those in-memory predicates reads the collection. One named organization
    is still get_organization, not this walk.

    Custom-field ids come from list_custom_fields. Match by definition id, not the
    label. A missing custom-field value is not a match.

    "Prospects", "current investors", and "former investors" are organizations, found by
    an organization status custom field (e.g. an "Investor Status" select) — not by
    opportunity stage, and not by search_opportunities. Read that field's options in
    list_custom_fields(entity_types=["organizations"]) and filter on the one the user
    named. A qualifier such as "active" usually maps to a second organization status
    field (dialogue or relationship stage): pass every option that counts as active in
    `values`, and state which options you applied. To group rows by Grade, Investor Type,
    or any other field, pass those ids as `custom_field_columns`.

    `coverage.visible_count` is Backstop's total for the server-side filters, before
    the in-memory predicates. An empty `rows` list means nothing matched.

    Call like: {"country": "Finland",
    "custom_fields": [{"definition_id": "261621", "values": ["Prospect"]}],
    "custom_field_columns": ["261623", "8646227"], "fields": ["name", "city", "country"]}
    """
    predicates = _predicates(custom_fields)
    chosen = frozenset(fields) if fields is not None else _DEFAULT_FIELDS
    with _tracer.start_as_current_span("org_people.search") as span:
        span.set_attribute("memory_custom_fields", len(predicates))
        logger.info(
            "org_people.search.start",
            extra={
                "name": name is not None,
                "email": email is not None,
                "other_id": other_id is not None,
                "matching_domain": matching_domain is not None,
                "legal_name": legal_name is not None,
                "city": city is not None,
                "country": country is not None,
                "state": state is not None,
                "website": website is not None,
                "ria": ria is not None,
                "internal_organization": internal_organization is not None,
                "custom_fields": len(predicates),
                "custom_field_columns": len(custom_field_columns or ()),
                "max_rows": max_rows,
            },
        )
        return await search_organizations_query.run(
            name=name,
            email=email,
            other_id=other_id,
            matching_domain=matching_domain,
            legal_name=legal_name,
            city=city,
            country=country,
            state=state,
            website=website,
            ria=ria,
            internal_organization=internal_organization,
            custom_fields=predicates,
            custom_field_columns=tuple(custom_field_columns or ()),
            max_rows=max_rows,
            fields=chosen,
        )
