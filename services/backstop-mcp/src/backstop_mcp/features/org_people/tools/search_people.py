"""`search_people`: firm-wide people filter.

`name`, `last_name`, `email`, `other_id`, and `email_domain` are sent to Backstop.
`first_name`, `job_title`, `company_name`, `department`, `location_filter`, `website`,
and custom fields are applied after the walk: those filter fields are 400 on
`GET /people`. A custom-field-only call reads the collection. Every person's contact
locations ride on that walk, so `location_filter` can match any address or the primary one.
"""

import logging
from collections.abc import Sequence
from typing import Annotated, Literal

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from opentelemetry import trace
from pydantic import BaseModel, Field

from backstop_mcp.features.custom_fields import CustomFieldMatch
from backstop_mcp.features.org_people import (
    MAX_PEOPLE_SCAN_RECORDS,
    SearchPeopleQuery,
    SearchPeopleResolvedResponse,
)
from backstop_mcp.features.org_people.dependencies import get_search_people_query_factory
from backstop_mcp.features.org_people.inputs import LocationFilter
from backstop_mcp.models import CoercedId, NonEmptyStr, published_output_schema

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

SearchPersonField = Literal[
    "id",
    "url",
    "name",
    "first_name",
    "last_name",
    "email",
    "email2",
    "email3",
    "job_title",
    "company_name",
    "department",
    "city",
    "country",
    "state",
    "postal_code",
    "street_address",
    "location_title",
    "locations",
    "website",
    "other_id",
]
_DEFAULT_FIELDS: frozenset[str] = frozenset(
    {"id", "name", "email", "job_title", "company_name", "city", "country", "locations"}
)


class PersonCustomFieldFilter(BaseModel):
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
    custom_fields: Sequence[PersonCustomFieldFilter] | None,
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
    output_schema=published_output_schema(SearchPeopleResolvedResponse),
)
async def search_people(
    name: Annotated[
        str | None,
        Field(
            description=(
                "Exact display name as stored, usually 'Last, First'. Sent to Backstop. "
                "Not a substring: 'Smith' matches nothing when the stored name is "
                "'Smith, Jane'. Use `last_name` for a substring of the last name."
            )
        ),
    ] = None,
    last_name: Annotated[
        str | None,
        Field(description="Substring of the last name. Sent to Backstop."),
    ] = None,
    email: Annotated[
        str | None,
        Field(
            description=(
                "Exact email. Looked up on email, email2, and email3 separately, then "
                "combined. A person stored on any of the three matches."
            )
        ),
    ] = None,
    other_id: Annotated[
        str | None,
        Field(description="otherId, exact. Sent to Backstop."),
    ] = None,
    email_domain: Annotated[
        str | None,
        Field(description="One email domain, exact. Sent to Backstop."),
    ] = None,
    first_name: Annotated[
        str | None,
        Field(description="Substring of the first name. Applied after the server-side read."),
    ] = None,
    job_title: Annotated[
        str | None,
        Field(description="Substring of the job title. Applied after the server-side read."),
    ] = None,
    company_name: Annotated[
        str | None,
        Field(
            description=(
                "Substring of the company-name text on the person record. Applied after "
                "the server-side read. Not a walk of that company's roster — that is "
                "get_people_for_party."
            )
        ),
    ] = None,
    department: Annotated[
        str | None,
        Field(description="Substring of the department. Applied after the server-side read."),
    ] = None,
    location_filter: Annotated[
        LocationFilter | None,
        Field(
            description=(
                "One location the person must have: any of city, country, state, "
                "postal_code, street_address, location_title, all matched against the same "
                "location. `city` and `street_address` are exact, case-sensitive and sent to "
                "Backstop; the others are case-insensitive substrings applied after the "
                "server-side read. By default any of the person's locations may match; set "
                "`primary_only` to read the primary one only. One location only: for several "
                "(London or Paris), make one call each and combine the rows."
            )
        ),
    ] = None,
    website: Annotated[
        str | None,
        Field(description="Substring of the website. Applied after the server-side read."),
    ] = None,
    custom_fields: Annotated[
        list[PersonCustomFieldFilter] | None,
        Field(
            description=(
                "Custom-field predicates, AND. Each is a definition id from "
                "list_custom_fields plus the stored value. Applied after the "
                "server-side read. A call that sets only "
                "these reads the collection (up to "
                f"{MAX_PEOPLE_SCAN_RECORDS} rows) and says so in `coverage`."
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
        list[SearchPersonField] | None,
        Field(
            description=(
                "Sparse row fields. Defaults to id, name, email, job_title, company_name, "
                "city, country, locations. `city`, `country`, `state`, `postal_code`, "
                "`street_address`, and `location_title` are the primary location; "
                "`locations` is every address. `id` is always included. Select `url` when "
                "the answer will link to the person — it is off by default. "
                "`custom_field_values` is included automatically unless "
                "`exclude_custom_fields` is set."
            )
        ),
    ] = None,
    search_people_query: SearchPeopleQuery = Depends(get_search_people_query_factory),
) -> SearchPeopleResolvedResponse:
    """Filter people across the firm.

    These are the contacts and employees of the organizations in the CRM (clients and
    investors), not our own colleagues. A colleague is a Backstop user: find them with
    list_system_users.

    `name`, `last_name`, `email`, `other_id`, and `email_domain` are sent to Backstop and
    narrow the read. `name` is the exact display name, usually 'Last, First' — not a
    substring. `last_name` is the substring. `email` is exact on email, email2, and email3.
    `first_name`, `job_title`, `company_name`, `department`, `website`, the rest of
    `location_filter`, and `custom_fields` are applied after that walk. The `city` and
    `street_address` of `location_filter` are sent to Backstop too. A call with only
    those in-memory predicates reads the collection. One named person is still get_person,
    not this walk. People at one organization are get_people_for_party. This reads
    `/people` only — a contacts or employees id is not a people id.

    `location_filter` is one location: every field in it must match the same address of
    the person. `city` and `street_address` must equal the stored value exactly, case included
    ('London', not 'london' or 'Lond'); the other fields are case-insensitive substrings.
    Any of the person's addresses may match —
    a London address that is not the primary one counts — unless `primary_only` is true.
    A person with no location matches no location filter.
    For several locations, call once per location and combine the rows.

    Custom-field ids come from list_custom_fields. Match by definition id, not the
    label. A missing custom-field value is not a match.

    Every row carries its custom fields as `custom_field_values`. If a call times out,
    retry once with `exclude_custom_fields=true` to see whether reading them is the cause;
    otherwise leave it false. Every row also carries its addresses as `locations`.

    `coverage.visible_count` is Backstop's total for the server-side filters, before
    the in-memory predicates. An empty `rows` list means nothing matched.

    Call like: {"last_name": "West",
    "custom_fields": [{"definition_id": "<definition id from list_custom_fields>",
    "values": ["<option from list_custom_fields>"]}],
    "fields": ["name", "job_title", "company_name", "locations"]}
    """
    if custom_fields and exclude_custom_fields:
        raise ValueError(
            "exclude_custom_fields cannot be combined with custom_fields: the filter reads them"
        )
    predicates = _predicates(custom_fields)
    chosen = frozenset(fields) if fields is not None else _DEFAULT_FIELDS
    with _tracer.start_as_current_span("org_people.search_people") as span:
        span.set_attribute("memory_custom_fields", len(predicates))
        logger.info(
            "org_people.search_people.start",
            extra={
                "has_name": name is not None,
                "last_name": last_name is not None,
                "email": email is not None,
                "other_id": other_id is not None,
                "email_domain": email_domain is not None,
                "first_name": first_name is not None,
                "job_title": job_title is not None,
                "company_name": company_name is not None,
                "department": department is not None,
                "location_filter": location_filter is not None,
                "website": website is not None,
                "custom_fields": len(predicates),
                "exclude_custom_fields": exclude_custom_fields,
            },
        )
        return await search_people_query.run(
            name=name,
            last_name=last_name,
            email=email,
            other_id=other_id,
            email_domain=email_domain,
            first_name=first_name,
            job_title=job_title,
            company_name=company_name,
            department=department,
            location_filter=location_filter,
            website=website,
            custom_fields=predicates,
            exclude_custom_fields=exclude_custom_fields,
            fields=chosen,
        )
