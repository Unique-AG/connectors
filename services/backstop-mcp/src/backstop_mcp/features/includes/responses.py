"""The trimmed models a side-loaded resource is projected onto, and the two models they fill.

These are the entity documentation. Every model carries a docstring and every field a
`description`, so FastMCP publishes them in the tools' output schema.

Every model leads with `id`, the JSON:API resource id of the record it projects. That is a
top-level member of a resource object rather than one of its attributes, which is why
`resolve._project` folds it in explicitly. Without it a projection is a dead end:
`ContactCardResponse` and `CompanyRefResponse` both tell the reader to call `get_person` /
`get_organization` for the full record, and both of those refuse a `party_id` they did not hand
out ("never invent or guess"), leaving only a name to search by and the ambiguity that comes with
it. The ids are in the right space for that — `primary_contact` side-loads `people` and `company`
side-loads `organizations`, which is what those two tools resolve against.

`extra="ignore"` does the trimming: a `contact-locations` resource ships 17 attributes and
`ContactLocationResponse` keeps 8; a person ships 31 and `ContactCardResponse` keeps 6. Where
Backstop stores one fact twice — `city`/`cityResolvedName`, `state`/`stateResolvedName`,
`country`/`countryResolvedName`, `isPrimaryLocation`/`primaryLocation` — only the plain name is
bound and the twin is dropped, so a reader is never left deciding which of two spellings to
believe.

`OrganizationIncludesResponse` and `PersonIncludesResponse` are also the allowlist. A field *is*
one exposed include: its `Include` metadata says what to ask Backstop for, and its annotation
says whether the answer is one record or many and what it projects onto — so `resolve` needs no
table beside them. A relationship with no field cannot be asked for at all (`activities` is
unreachable by construction rather than by a runtime check), and the `Literal` alias beside each
model is what the tools type their `include` parameter as, so an invalid name is rejected at the
MCP boundary and the input schema lists the options.

Include names are ours, not Backstop's, wherever Backstop's would mislead. Backstop's `emails`
relationship is email *messages* (488 on one organization); the address book is `contactEmails`.
An include literally named `emails` would invite a model to pull hundreds of messages while
looking for an address, so it is exposed as `email_addresses`.
"""

from collections.abc import Mapping, Sequence
from typing import Annotated, ClassVar, Literal, cast

from pydantic import BeforeValidator, ConfigDict, Field

from backstop_mcp.features.includes.types import Include
from backstop_mcp.models import OmitNoneModel


def _blank_to_none(value: object) -> object:
    """Backstop sends `""` where it means "unset" — `fax` and `secondaryPhoneNumber` both do."""
    return (value.strip() or None) if isinstance(value, str) else value


def _mapping_name(item: Mapping[object, object]) -> str | None:
    raw_name = item.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()
    return None


def _categories(value: object) -> object:
    """Accept a list of strings or `{name}` objects; empty becomes None."""
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    names: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
        elif isinstance(item, Mapping):
            raw_name = _mapping_name(cast("Mapping[object, object]", item))
            if raw_name is not None:
                names.append(raw_name)
    return tuple(names) or None


# Annotated on the *union*, not on the `str` arm: a `BeforeValidator` inside
# `Annotated[str, ...] | None` still has its result checked against `str`, so returning None for
# a blank fails validation rather than selecting the None arm.
_CleanStr = Annotated[str | None, BeforeValidator(_blank_to_none)]

_PROJECTION_CONFIG = ConfigDict(extra="ignore", populate_by_name=True)


class ContactLocationResponse(OmitNoneModel):
    """A postal address on file for a person or organization.

    One entry per address Backstop holds, labelled by `location_title` ("Business", "Home"), with
    the phone number that belongs to that address. Backstop's secondary phone number and fax are
    not exposed.
    """

    model_config: ClassVar[ConfigDict] = _PROJECTION_CONFIG

    id: _CleanStr = Field(
        default=None,
        description="Backstop `contact-locations` id for this address.",
    )
    location_title: _CleanStr = Field(
        default=None,
        alias="locationTitle",
        description="What this address is, as labelled in Backstop — e.g. 'Business', 'Home'.",
    )
    address: _CleanStr = Field(
        default=None,
        description="Street address, including any suite or floor.",
    )
    city: _CleanStr = Field(default=None, description="City.")
    state: _CleanStr = Field(
        default=None,
        description="State or province, usually as a code such as 'AZ'.",
    )
    country: _CleanStr = Field(
        default=None,
        description="Country, spelled out — e.g. 'United States of America'.",
    )
    postal_code: _CleanStr = Field(
        default=None, alias="postalCode", description="Postal or ZIP code."
    )
    phone: _CleanStr = Field(
        default=None,
        alias="phoneNumber",
        description="Phone number for this address, not for the contact in general.",
    )
    is_primary: bool | None = Field(
        default=None,
        alias="isPrimaryLocation",
        description="Whether Backstop marks this as the contact's primary address.",
    )


class ContactEmailResponse(OmitNoneModel):
    """One email address from a contact's address book.

    Not an email *message*: Backstop's `emails` relationship holds correspondence (hundreds of
    it per organization) and is a different thing entirely. Retired addresses are returned
    alongside live ones so past correspondence stays explainable — read `retired` before using
    one.
    """

    model_config: ClassVar[ConfigDict] = _PROJECTION_CONFIG

    id: _CleanStr = Field(
        default=None,
        description="Backstop `contact-emails` id for this address book entry.",
    )
    email: _CleanStr = Field(default=None, description="The email address.")
    # No default: an address whose status is unknown is worse than one that is missing. A
    # `contact-emails` resource without `retired` fails validation and is dropped by the
    # projection in `resolve`, rather than being handed over as if it were live.
    retired: bool = Field(
        description=(
            "True when Backstop has retired this address: do NOT send mail to it. Retired "
            + "addresses are kept for history and may belong to the contact's previous firm, or "
            + "even to a different person. False means the address is current."
        )
    )


class ContactCardResponse(OmitNoneModel):
    """Who a person is, in the few fields needed to recognise and reach them.

    A summary attached to another record (an organization's primary contact), not the full
    person — call `get_person` with this record's `id` for that.
    """

    model_config: ClassVar[ConfigDict] = _PROJECTION_CONFIG

    id: _CleanStr = Field(
        default=None,
        description=(
            "Backstop person id. Pass it as `party_id` to `get_person` for the full record — it "
            + "is a `people` id, so leave `search_type` at its default. Use this rather than "
            + "searching by name: the name alone can match more than one person."
        ),
    )
    name: _CleanStr = Field(
        default=None,
        description="Display name as Backstop stores it, usually 'Last, First'.",
    )
    job_title: _CleanStr = Field(
        default=None, alias="jobTitle", description="Job title at their organization."
    )
    email: _CleanStr = Field(
        default=None,
        description=(
            "Primary email address on the person record. The full address book, including "
            + "retired addresses, is the `email_addresses` include on `get_person`."
        ),
    )
    phone: _CleanStr = Field(default=None, description="Primary phone number.")
    company_name: _CleanStr = Field(
        default=None,
        alias="companyName",
        description="Name of the organization the person works at.",
    )
    categories: Annotated[tuple[str, ...] | None, BeforeValidator(_categories)] = Field(
        default=None,
        description=(
            "CRM categories on this person — investor type, role, or similar labels. "
            "Omitted when Backstop sends none."
        ),
    )


class CompanyRefResponse(OmitNoneModel):
    """The organization a person works at, in the few fields needed to identify it.

    A summary attached to a person record, not the full organization — call `get_organization`
    with this record's `id` for that.
    """

    model_config: ClassVar[ConfigDict] = _PROJECTION_CONFIG

    id: _CleanStr = Field(
        default=None,
        description=(
            "Backstop organization id. Pass it as `party_id` to `get_organization` for the full "
            + "record. Use this rather than searching by name: the name alone can match more "
            + "than one organization."
        ),
    )
    name: _CleanStr = Field(default=None, description="Organization name as commonly used.")
    legal_name: _CleanStr = Field(
        default=None,
        alias="legalName",
        description="Registered legal name, when it differs from the common name.",
    )
    website: _CleanStr = Field(default=None, description="Organization website.")
    city: _CleanStr = Field(default=None, description="City of the organization's address.")
    state: _CleanStr = Field(default=None, description="State or province, usually as a code.")
    country: _CleanStr = Field(default=None, description="Country, spelled out.")


class InternalOwnerResponse(OmitNoneModel):
    """The colleague at *our* firm who owns this relationship.

    A Backstop `system-users` record — one of our own staff, not the investor. Every field here
    is an internal detail: `email` and `phone` reach our account owner at our own office, and
    are not a way to contact the person or organization this is attached to. Their details are
    on the record itself and on the `locations` / `email_addresses` includes.
    """

    model_config: ClassVar[ConfigDict] = _PROJECTION_CONFIG

    id: _CleanStr = Field(
        default=None,
        description="Backstop `system-users` id for this colleague at our own firm.",
    )
    name: _CleanStr = Field(default=None, description="Full name of our account owner.")
    user_name: _CleanStr = Field(
        default=None, alias="userName", description="Their Backstop login name."
    )
    email: _CleanStr = Field(
        default=None, description="Their work email address at our firm, not the investor's."
    )
    phone: _CleanStr = Field(
        default=None, alias="phoneNumber", description="Their office phone number at our firm."
    )
    disabled: bool | None = Field(
        default=None,
        description=(
            "True when this colleague's login is disabled. Do not treat their empty pipeline "
            "as 'no coverage' — the filter matched a departed login."
        ),
    )


type OrganizationInclude = Literal[
    "locations", "email_addresses", "primary_contact", "representative"
]


class OrganizationIncludesResponse(OmitNoneModel):
    """The related records side-loaded with an organization, one field per `include` value.

    Every field distinguishes three answers, and none of them is `null` — a field with no value
    is left out of the payload entirely. An **omitted** key means the include was not requested —
    we did not look, or, for a single record, there is nothing on file. `[]` means a list include
    was requested and there is nothing on file — we looked, there are none. A value is what was
    requested and found.
    """

    locations: Annotated[
        list[ContactLocationResponse] | None,
        Include(relationship="contactLocations", resource_type="contact-locations"),
    ] = Field(
        default=None,
        description=(
            "Postal addresses on file for the organization, from `include=locations`. Omitted "
            + "when that include was not asked for; `[]` when it was and there are no addresses."
        ),
    )
    email_addresses: Annotated[
        list[ContactEmailResponse] | None,
        Include(relationship="contactEmails", resource_type="contact-emails"),
    ] = Field(
        default=None,
        description=(
            "The organization's email address book, from `include=email_addresses` — addresses, "
            + "not correspondence. Omitted when that include was not asked for; `[]` when it was "
            + "and there are no addresses."
        ),
    )
    primary_contact: Annotated[
        ContactCardResponse | None,
        Include(relationship="primaryContact", resource_type="people"),
    ] = Field(
        default=None,
        description=(
            "The person Backstop names as the organization's main point of contact, from "
            + "`include=primary_contact`. Omitted when that include was not asked for and "
            + "equally when it was and no primary contact is set."
        ),
    )
    representative: Annotated[
        InternalOwnerResponse | None,
        Include(relationship="representative", resource_type="system-users"),
    ] = Field(
        default=None,
        description=(
            "The colleague at our own firm who owns this relationship, from "
            + "`include=representative` — not a way to contact the organization. Omitted when "
            + "that include was not asked for and equally when it was and nobody is assigned."
        ),
    )


type PersonInclude = Literal["locations", "email_addresses", "company", "representative"]


class PersonIncludesResponse(OmitNoneModel):
    """The related records side-loaded with a person, one field per `include` value.

    Every field distinguishes three answers, and none of them is `null` — a field with no value
    is left out of the payload entirely. An **omitted** key means the include was not requested —
    we did not look, or, for a single record, there is nothing on file. `[]` means a list include
    was requested and there is nothing on file — we looked, there are none. A value is what was
    requested and found.
    """

    locations: Annotated[
        list[ContactLocationResponse] | None,
        Include(relationship="contactLocations", resource_type="contact-locations"),
    ] = Field(
        default=None,
        description=(
            "Postal addresses on file for the person, from `include=locations`. Omitted when "
            + "that include was not asked for; `[]` when it was and there are no addresses."
        ),
    )
    email_addresses: Annotated[
        list[ContactEmailResponse] | None,
        Include(relationship="contactEmails", resource_type="contact-emails"),
    ] = Field(
        default=None,
        description=(
            "The person's email address book, from `include=email_addresses` — addresses, not "
            + "correspondence, and retired addresses are flagged rather than hidden. Omitted "
            + "when that include was not asked for; `[]` when it was and there are no addresses."
        ),
    )
    company: Annotated[
        CompanyRefResponse | None,
        Include(relationship="company", resource_type="organizations"),
    ] = Field(
        default=None,
        description=(
            "The organization the person works at, from `include=company`. Omitted when that "
            + "include was not asked for and equally when it was and no organization is linked."
        ),
    )
    representative: Annotated[
        InternalOwnerResponse | None,
        Include(relationship="representative", resource_type="system-users"),
    ] = Field(
        default=None,
        description=(
            "The colleague at our own firm who owns this relationship, from "
            + "`include=representative` — not a way to contact the person. Omitted when that "
            + "include was not asked for and equally when it was and nobody is assigned."
        ),
    )


class ActivityTagChipResponse(OmitNoneModel):
    """One activity tag side-loaded onto an activity row."""

    model_config: ClassVar[ConfigDict] = _PROJECTION_CONFIG

    id: _CleanStr = Field(
        default=None,
        description=(
            "Backstop id of this activity tag. Echo it into activity_tag_ids; never invent one."
        ),
    )
    name: _CleanStr = Field(default=None, description="Tag name as Backstop publishes it.")


class ActivityAttendeeResponse(OmitNoneModel):
    """A person listed on a meeting or call, side-loaded from `include=attendees`."""

    model_config: ClassVar[ConfigDict] = _PROJECTION_CONFIG

    id: _CleanStr = Field(
        default=None,
        description=(
            "Backstop people id. Pass it as party_id to get_person for the full record. "
            "Omitted when the side-load has no id."
        ),
    )
    name: _CleanStr = Field(default=None, description="Display name as Backstop stores it.")


type ActivityInclude = Literal["activity_tags", "attendees"]


class ActivityIncludesResponse(OmitNoneModel):
    """Related records side-loaded with an activity row, one field per include.

    Always requested on get_activity_history's meeting/call/note/document pages. Notes and
    documents have no attendees relationship; that field is then `[]`. Emails do not support
    includes and are not projected through this model.
    """

    activity_tags: Annotated[
        list[ActivityTagChipResponse] | None,
        Include(relationship="activityTags", resource_type="activity-tags"),
    ] = Field(
        default=None,
        description=(
            "Tags on this activity, from include=activityTags. Omitted when that include was "
            "not asked for; [] when it was and the activity has no tags."
        ),
    )
    attendees: Annotated[
        list[ActivityAttendeeResponse] | None,
        Include(relationship="attendees", resource_type="people"),
    ] = Field(
        default=None,
        description=(
            "People listed on a meeting or call, from include=attendees. Omitted when that "
            "include was not asked for; [] when it was and there are none, including on notes "
            "and documents which have no attendees relationship."
        ),
    )
