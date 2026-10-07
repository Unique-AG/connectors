"""`search_organizations`: firm-wide organization filter.

`name`, `email`, `other_id`, and `matching_domain` are sent to Backstop.
`legal_name`, `location_filter`, `website`, `ria`, `internal_organization`, and custom
fields are applied after the walk: those filter fields are 400 on `GET /organizations`.
A custom-field-only call reads the collection. Every organization's contact locations ride
on that walk, so `location_filter` can match any office or the primary one. One call returns
one page of matches; `cursor` resumes at the next unread record.
"""

import logging
from collections.abc import Sequence
from typing import Annotated, Literal

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from opentelemetry import trace
from pydantic import BaseModel, Field

from backstop_mcp.config import SearchConfig
from backstop_mcp.dependencies import get_search_config
from backstop_mcp.features.custom_fields import CustomFieldMatch
from backstop_mcp.features.org_people import (
    SearchOrganizationsQuery,
    SearchOrganizationsResolvedResponse,
)
from backstop_mcp.features.org_people.dependencies import get_search_organizations_query_factory
from backstop_mcp.features.org_people.inputs import LocationFilter
from backstop_mcp.models import CoercedId, NonEmptyStr, published_output_schema

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

SearchOrganizationField = Literal[
    "id",
    "url",
    "name",
    "legal_name",
    "email",
    "city",
    "country",
    "state",
    "postal_code",
    "street_address",
    "location_title",
    "locations",
    "website",
    "other_id",
    "matching_domains",
    "ria",
    "internal_organization",
]
_DEFAULT_FIELDS: frozenset[str] = frozenset(
    {"id", "name", "legal_name", "email", "city", "country", "locations"}
)


class OrganizationCustomFieldFilter(BaseModel):
    """One custom-field predicate. Several predicates AND together."""

    definition_id: CoercedId = Field(
        description=(
            "Custom-field definition id from list_custom_fields. Not the field label: "
            "two definitions can share a name."
        )
    )
    values: list[NonEmptyStr] = Field(
        min_length=1,
        description=(
            "Stored values that satisfy this predicate, OR. Each is compared whole and "
            "case-insensitively against the select options list_custom_fields returns — "
            "pass every option that counts, "
            "not a substring. A list value matches when any element equals one of these. "
            "A missing value does not match — this filter cannot mean 'the field is empty'."
        ),
    )


def _predicates(
    custom_fields: Sequence[OrganizationCustomFieldFilter] | None,
) -> tuple[CustomFieldMatch, ...]:
    if not custom_fields:
        return ()
    return tuple(
        CustomFieldMatch(definition_id=item.definition_id, values=tuple(item.values))
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
        Field(description=("Substring of the organization name. Not a prefix-only quick search.")),
    ] = None,
    email: Annotated[
        str | None,
        Field(description=("Primary email, exact. email2 and email3 are not matched.")),
    ] = None,
    other_id: Annotated[
        str | None,
        Field(description="otherId, exact."),
    ] = None,
    matching_domain: Annotated[
        str | None,
        Field(description="One email domain, exact."),
    ] = None,
    legal_name: Annotated[
        str | None,
        Field(description=("Substring of the legal name. Applied after the server-side read.")),
    ] = None,
    location_filter: Annotated[
        LocationFilter | None,
        Field(
            description=(
                "One location the organization must have: any of city, country, state, "
                "postal_code, street_address, location_title, all matched against the same "
                "location. `city` and `street_address` are exact, case-sensitive and sent to "
                "Backstop; `state` is the whole value and `country` whole words, any case; "
                "the rest are case-insensitive substrings. All but city and street are applied "
                "after the server-side read. By default any of the organization's locations "
                "may match; set `primary_only` to read the primary one only. One location "
                "only: for several (London or Paris), make one call each and combine the rows."
            )
        ),
    ] = None,
    website: Annotated[
        str | None,
        Field(description=("Substring of the website. Applied after the server-side read.")),
    ] = None,
    ria: Annotated[
        bool | None,
        Field(description="Exact RIA flag. Applied after the server-side read."),
    ] = None,
    internal_organization: Annotated[
        bool | None,
        Field(
            description=("Exact internal-organization flag. Applied after the server-side read.")
        ),
    ] = None,
    custom_fields: Annotated[
        list[OrganizationCustomFieldFilter] | None,
        Field(
            description=(
                "Custom-field predicates, AND. Each is a definition id from "
                "list_custom_fields plus the stored value. Applied after the "
                "server-side read, so a call that sets only these reads the collection until "
                "the page fills."
            )
        ),
    ] = None,
    exclude_custom_fields: Annotated[
        bool,
        Field(
            description=(
                "Every row's custom fields come back as `custom_field_values` by default — "
                "the fields a table is grouped or labelled by. Leave "
                "this false. Set it true only to retry a call that timed out, to see whether "
                "reading the custom fields is what made it slow. Refused together with "
                "`custom_fields`, which needs them."
            )
        ),
    ] = False,
    fields: Annotated[
        list[SearchOrganizationField] | None,
        Field(
            description=(
                "Sparse row fields. Defaults to id, name, legal_name, email, city, "
                "country, locations. `city`, `country`, `state`, `postal_code`, "
                "`street_address`, and `location_title` are the primary location; "
                "`locations` is every address. `id` is always included. Select `url` when "
                "the answer will link to the organization — it is off by default. "
                "`custom_field_values` is included automatically unless "
                "`exclude_custom_fields` is set."
            )
        ),
    ] = None,
    cursor: Annotated[
        str | None,
        Field(
            description=(
                "`continuation.cursor` from the previous page of this same search. Repeat "
                "every other argument unchanged; a cursor from different arguments is rejected."
            )
        ),
    ] = None,
    search_organizations_query: SearchOrganizationsQuery = Depends(
        get_search_organizations_query_factory
    ),
    search_config: SearchConfig = Depends(get_search_config),
) -> SearchOrganizationsResolvedResponse:
    """Filter organizations across the firm.

    `name`, `email`, `other_id`, and `matching_domain` are sent to Backstop and narrow
    the read, and so do the `city` and `street_address` of `location_filter`.
    `legal_name`, the rest of `location_filter`, `website`, `ria`, `internal_organization`,
    and `custom_fields` are applied after that walk. A call with only those in-memory
    predicates reads the collection. One named organization is still get_organization,
    not this walk.

    `location_filter` is one location: every field in it must match the same address of
    the organization. `city` and `street_address` must equal the stored value exactly, case
    included ('London', not 'london' or 'Lond'); `state` is the whole value and `country`
    whole words, any case; the other fields are case-insensitive substrings. Any of the
    organization's locations may match — a London office that is not the primary one counts — unless
    `primary_only` is true. An organization with no location matches no location filter.
    For several locations, call once per location and combine the rows.

    Custom-field ids come from list_custom_fields. Match by definition id, not the
    label. A missing custom-field value is not a match.

    Every row carries its custom fields as `custom_field_values`. If a call times out,
    retry once with `exclude_custom_fields=true` to see whether reading them is the cause;
    otherwise leave it false. Every row also carries its addresses as `locations`.

    One call returns one page of rows in Backstop id order, not by name. `continuation`
    means the page stopped before the end: follow `continuation.cursor`, with every other
    argument unchanged, only when the user needs more rows than this page holds. An empty
    `rows` list means nothing matched.
    `coverage.visible_count` is Backstop's total for the server-side filters, before
    the in-memory predicates.

    Call like: {"location_filter": {"country": "Finland"},
    "custom_fields": [{"definition_id": "<definition id from list_custom_fields>",
    "values": ["<option from list_custom_fields>"]}],
    "fields": ["name", "locations"]}
    """
    if custom_fields and exclude_custom_fields:
        raise ValueError(
            "exclude_custom_fields cannot be combined with custom_fields: the filter reads them"
        )
    predicates = _predicates(custom_fields)
    chosen = frozenset(fields) if fields is not None else _DEFAULT_FIELDS
    with _tracer.start_as_current_span("org_people.search") as span:
        span.set_attribute("memory_custom_fields", len(predicates))
        logger.info(
            "org_people.search.start",
            extra={
                "has_name": name is not None,
                "email": email is not None,
                "other_id": other_id is not None,
                "matching_domain": matching_domain is not None,
                "legal_name": legal_name is not None,
                "location_filter": location_filter is not None,
                "website": website is not None,
                "ria": ria is not None,
                "internal_organization": internal_organization is not None,
                "custom_fields": len(predicates),
                "exclude_custom_fields": exclude_custom_fields,
                "cursor": cursor is not None,
            },
        )
        return await search_organizations_query.run(
            name=name,
            email=email,
            other_id=other_id,
            matching_domain=matching_domain,
            legal_name=legal_name,
            location_filter=location_filter,
            website=website,
            ria=ria,
            internal_organization=internal_organization,
            custom_fields=predicates,
            exclude_custom_fields=exclude_custom_fields,
            fields=chosen,
            result_size=search_config.result_size,
            cursor=cursor,
        )
