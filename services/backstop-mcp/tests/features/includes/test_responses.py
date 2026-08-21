"""The projection models and the two includes models: what they keep, drop, refuse and publish.

Payloads here are the live instance's, field for field.
"""

from typing import cast, get_args

import pytest
from pydantic import BaseModel, ValidationError

from backstop_mcp.features.includes import (
    ActivityInclude,
    ActivityIncludesResponse,
    CompanyRefResponse,
    ContactCardResponse,
    ContactEmailResponse,
    ContactLocationResponse,
    Include,
    InternalOwnerResponse,
    OrganizationInclude,
    OrganizationIncludesResponse,
    PersonInclude,
    PersonIncludesResponse,
)


def _dictionary(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return {str(key): entry for key, entry in cast("dict[object, object]", value).items()}


def _literal_names(alias: object) -> tuple[str, ...]:
    """The members of a PEP 695 `type X = Literal[...]` alias, in order."""
    value: object = getattr(alias, "__value__", alias)
    members: tuple[object, ...] = get_args(value)
    return tuple(str(member) for member in members)


def _includes(model: type[BaseModel]) -> dict[str, Include]:
    """The `Include` each field of an includes model carries."""
    return {
        name: meta
        for name, field in model.model_fields.items()
        for meta in cast(list[object], field.metadata)
        if isinstance(meta, Include)
    }


def _defs_descriptions(model: type[BaseModel]) -> set[str]:
    """Every field description the model's JSON schema publishes under `$defs`."""
    definitions = _dictionary(_dictionary(model.model_json_schema())["$defs"])
    return {
        description
        for definition in definitions.values()
        for field in _dictionary(_dictionary(definition)["properties"]).values()
        if isinstance(description := _dictionary(field).get("description"), str)
    }


def _field_descriptions(model: type[BaseModel]) -> set[str]:
    return {field.description for field in model.model_fields.values() if field.description}


_LOCATION: dict[str, object] = {
    "country": "United States of America",
    "countryResolvedName": "United States of America",
    "address": "18867 North Thompson Peak Parkway, Suite 250",
    "city": "Scottsdale",
    "postalCode": "85255",
    "createdTimestamp": "2019-01-01T00:00:00Z",
    "locationTitle": "Business",
    "isPrimaryLocation": True,
    "secondaryPhoneNumber": "",
    "cityResolvedName": "Scottsdale",
    "stateResolvedName": "AZ",
    "phoneNumber": "(480) 419-3625",
    "countryCode": "US",
    "primaryLocation": True,
    "modifiedTimestamp": "2020-01-01T00:00:00Z",
    "state": "AZ",
    "fax": "",
}

_PERSON: dict[str, object] = {
    "country": "United States",
    "lastName": "Voss",
    "gender": "UNSPECIFIED",
    "city": "Scottsdale",
    "prefix": "",
    "jobTitle": "Managing Director, Research",
    "companyName": "Koch Industries Employees' Pension Plan",
    "postalCode": "85255",
    "suffix": "",
    "email3": "",
    "legalName": "Kent Voss",
    "email2": "",
    "state": "AZ",
    "fax": "",
    "syncDisabled": False,
    "email": "vossk@kochinvests.com",
    "isEmployee": False,
    "otherId": "59DB5FF3D01344A6806CF3BA99FD4FE2",
    "nickName": "",
    "createdTimestamp": "2013-06-12T20:15:35.000-0400",
    "locationTitle": "Business",
    "primaryPhoneNumber": "(480) 419-3625",
    "firstName": "Kent",
    "mobilePhone": "(480) 205-2506",
    "investableAssets": 0.0,
    "phone": "(480) 419-3625",
    "streetAddress": "18867 North Thompson Peak Parkway, Suite 250",
    "name": "Voss, Kent",
    "modifiedTimestamp": "2026-08-06T11:07:37.852-0400",
    "middleName": "",
    "regularCustomFieldValues": [],
}

_SYSTEM_USER: dict[str, object] = {
    "lastName": "Lucas",
    "targetCurrency": "USD",
    "dateFormat": "M/d/yyyy",
    "enabledUserFeatures": [],
    "fullName": "Margaret Lucas",
    "timeZone": "(6:24 AM) US/Eastern: Eastern Standard Time",
    "userName": "mlucas",
    "firstName": "Margaret",
    "phoneNumber": "12122321462",
    "name": "Margaret Lucas",
    "disabled": False,
    "email": "margaret.lucas@capstoneco.com",
    "isBsgAdmin": False,
}

_ORGANIZATION: dict[str, object] = {
    "country": "United States of America",
    "internalOrganization": False,
    "city": "Scottsdale",
    "postalCode": "85255",
    "ria": False,
    "legalName": "",
    "state": "AZ",
    "fax": "",
    "syncDisabled": False,
    "email": "",
    "website": "www.kbslp.com",
    "createdTimestamp": "2013-06-17T08:53:24.000-0400",
    "locationTitle": "Business",
    "primaryPhoneNumber": "(480) 419-3625",
    "numberOfEmployees": 0,
    "investableAssets": 9660000000.0,
    "phone": "(480) 419-3625",
    "streetAddress": "18867 North Thompson Peak Parkway, Suite 250",
    "name": "Koch Industries Employees' Pension Plan",
    "modifiedTimestamp": "2026-08-03T16:36:17.820-0400",
    "hasRecommendationViewed": True,
    "contactDescription": (
        "Koch Industries (~$11bn AUM) is a Wichita, Kansas-based multinational conglomerate."
    ),
    "groupEntities": [],
    "matchingDomains": [],
    "regularCustomFieldValues": [],
}


@pytest.mark.parametrize(
    "model",
    [
        ContactLocationResponse,
        ContactEmailResponse,
        ContactCardResponse,
        CompanyRefResponse,
        InternalOwnerResponse,
    ],
)
def test_every_field_is_documented(model: type[BaseModel]) -> None:
    """The models are the entity documentation, so a field without one is a hole in it."""
    assert all(field.description for field in model.model_fields.values())


class TestContactLocation:
    def test_keeps_eight_of_the_seventeen_attributes(self) -> None:
        location = ContactLocationResponse.model_validate(_LOCATION)

        assert location.model_dump() == {
            "location_title": "Business",
            "address": "18867 North Thompson Peak Parkway, Suite 250",
            "city": "Scottsdale",
            "state": "AZ",
            "country": "United States of America",
            "postal_code": "85255",
            "phone": "(480) 419-3625",
            "is_primary": True,
        }

    def test_collapses_each_duplicated_field_to_one(self) -> None:
        """Backstop ships four literal duplicate pairs; only the plain name is exposed."""
        dumped = ContactLocationResponse.model_validate(_LOCATION).model_dump()

        assert not {
            "countryResolvedName",
            "cityResolvedName",
            "stateResolvedName",
            "primaryLocation",
        } & set(dumped)

    def test_blank_strings_are_absence_not_a_value(self) -> None:
        location = ContactLocationResponse.model_validate({**_LOCATION, "phoneNumber": "  "})

        assert location.phone is None


class TestContactEmail:
    def test_keeps_the_address_and_its_retired_flag(self) -> None:
        email = ContactEmailResponse.model_validate(
            {"sortOrder": 0, "retired": True, "email": "bbetten@macfound.org"}
        )

        assert email.model_dump() == {"email": "bbetten@macfound.org", "retired": True}

    def test_a_live_address_is_distinguishable_from_a_retired_one(self) -> None:
        live = ContactEmailResponse.model_validate(
            {"sortOrder": 0, "retired": False, "email": "vossk@kochinvests.com"}
        )

        assert live.retired is False

    def test_an_address_with_no_retired_flag_is_rejected(self) -> None:
        """Unlabelled is worse than missing: a wrong address must not read as usable."""
        with pytest.raises(ValidationError):
            ContactEmailResponse.model_validate({"email": "kent.voss@kochind.com"})

    def test_the_retired_description_says_not_to_use_the_address(self) -> None:
        description = ContactEmailResponse.model_fields["retired"].description

        assert description is not None
        assert "do NOT send mail to it" in description


class TestContactCard:
    def test_keeps_five_person_attributes_when_categories_are_absent(self) -> None:
        card = ContactCardResponse.model_validate(_PERSON)

        assert card.model_dump() == {
            "name": "Voss, Kent",
            "job_title": "Managing Director, Research",
            "email": "vossk@kochinvests.com",
            "phone": "(480) 419-3625",
            "company_name": "Koch Industries Employees' Pension Plan",
        }

    def test_projects_categories_from_names_or_name_objects(self) -> None:
        from_strings = ContactCardResponse.model_validate(
            {"name": "Glenn, Phil", "categories": ["Investor", "Decision Maker"]}
        )
        from_objects = ContactCardResponse.model_validate(
            {
                "name": "Glenn, Phil",
                "categories": [{"name": "Investor"}, {"name": "  Decision Maker  "}, {"name": ""}],
            }
        )

        assert from_strings.categories == ("Investor", "Decision Maker")
        assert from_objects.categories == ("Investor", "Decision Maker")


class TestCompanyRef:
    def test_keeps_six_of_the_twenty_five_organization_attributes(self) -> None:
        """`legalName` is blank on this organization, so it reads as absent rather than as ''."""
        company = CompanyRefResponse.model_validate(_ORGANIZATION)

        assert company.model_dump() == {
            "name": "Koch Industries Employees' Pension Plan",
            "website": "www.kbslp.com",
            "city": "Scottsdale",
            "state": "AZ",
            "country": "United States of America",
        }


class TestInternalOwner:
    def test_keeps_five_of_the_thirteen_system_user_attributes(self) -> None:
        owner = InternalOwnerResponse.model_validate(_SYSTEM_USER)

        assert owner.model_dump() == {
            "name": "Margaret Lucas",
            "user_name": "mlucas",
            "email": "margaret.lucas@capstoneco.com",
            "phone": "12122321462",
            "disabled": False,
        }

    def test_is_documented_as_our_own_staff_rather_than_a_way_to_reach_the_investor(self) -> None:
        docstring = InternalOwnerResponse.__doc__

        assert docstring is not None
        assert "not the investor" in docstring


@pytest.mark.parametrize(
    "model",
    [
        ContactLocationResponse,
        ContactCardResponse,
        CompanyRefResponse,
        InternalOwnerResponse,
    ],
)
def test_the_id_is_optional_so_a_bare_attributes_payload_still_validates(
    model: type[BaseModel],
) -> None:
    """`id` is a resource member, not an attribute — a payload without one is still readable.

    Through `project` a record always has one, because `follow_included` found it by that id.
    `ContactEmailResponse` is excluded: it requires `retired` for its own reasons.
    """
    projected = model.model_validate({})

    assert projected.model_dump() == {}


class TestTheIncludesModelsAreTheAllowlist:
    """One field per exposed include, and the field's metadata is the whole Backstop side."""

    def test_the_organization_literal_lists_exactly_the_model_fields(self) -> None:
        """The `Literal` is what the tools accept; the model is what they can then resolve."""
        assert _literal_names(OrganizationInclude) == tuple(
            OrganizationIncludesResponse.model_fields
        )

    def test_the_person_literal_lists_exactly_the_model_fields(self) -> None:
        assert _literal_names(PersonInclude) == tuple(PersonIncludesResponse.model_fields)

    def test_the_activity_literal_lists_exactly_the_model_fields(self) -> None:
        assert _literal_names(ActivityInclude) == tuple(ActivityIncludesResponse.model_fields)

    def test_every_activity_field_asks_backstop_for_one_named_relationship(self) -> None:
        assert {
            name: (include.relationship, include.resource_type)
            for name, include in _includes(ActivityIncludesResponse).items()
        } == {
            "activity_tags": ("activityTags", "activity-tags"),
            "attendees": ("attendees", "people"),
        }

    def test_every_organization_field_asks_backstop_for_one_named_relationship(self) -> None:
        assert {
            name: (include.relationship, include.resource_type)
            for name, include in _includes(OrganizationIncludesResponse).items()
        } == {
            "locations": ("contactLocations", "contact-locations"),
            "email_addresses": ("contactEmails", "contact-emails"),
            "primary_contact": ("primaryContact", "people"),
            "representative": ("representative", "system-users"),
        }

    def test_every_person_field_asks_backstop_for_one_named_relationship(self) -> None:
        assert {
            name: (include.relationship, include.resource_type)
            for name, include in _includes(PersonIncludesResponse).items()
        } == {
            "locations": ("contactLocations", "contact-locations"),
            "email_addresses": ("contactEmails", "contact-emails"),
            "company": ("company", "organizations"),
            "representative": ("representative", "system-users"),
        }

    def test_no_field_exposes_an_unbounded_relationship(self) -> None:
        """`activities` is unreachable by construction, which is the point of the allowlist."""
        relationships = {
            include.relationship
            for model in (
                OrganizationIncludesResponse,
                PersonIncludesResponse,
                ActivityIncludesResponse,
            )
            for include in _includes(model).values()
        }

        assert "activities" not in relationships

    def test_the_address_book_is_exposed_not_the_message_history(self) -> None:
        """Backstop's `emails` is correspondence; `contactEmails` is the address book."""
        includes = _includes(OrganizationIncludesResponse)

        assert "emails" not in {include.relationship for include in includes.values()}
        assert "emails" not in includes
        assert includes["email_addresses"].relationship == "contactEmails"

    def test_every_field_defaults_to_not_looked(self) -> None:
        """`None` by default is what makes "not requested" distinguishable from "none found".

        Serialization drops those Nones (`OmitNoneModel`), so "not requested" is an omitted
        key on the wire — asserted separately from the in-memory default.
        """
        empty_org = OrganizationIncludesResponse()
        empty_person = PersonIncludesResponse()
        empty_activity = ActivityIncludesResponse()
        assert all(
            getattr(empty_org, name) is None for name in OrganizationIncludesResponse.model_fields
        )
        assert all(
            getattr(empty_person, name) is None for name in PersonIncludesResponse.model_fields
        )
        assert all(
            getattr(empty_activity, name) is None for name in ActivityIncludesResponse.model_fields
        )
        assert empty_org.model_dump() == {}
        assert empty_person.model_dump() == {}

    def test_every_field_is_documented_for_the_output_schema(self) -> None:
        fields = list(OrganizationIncludesResponse.model_fields.values()) + list(
            PersonIncludesResponse.model_fields.values()
        )

        assert all(field.description for field in fields)


class TestTheIncludeMetadataStaysOutOfThePublishedSchema:
    """Why `Include` is a plain dataclass: a `BaseModel` in the `Annotated` chain replaces the
    field's schema with a `$ref` to itself, and the projected type — with every description
    below — disappears from what FastMCP publishes.
    """

    def test_a_to_many_field_publishes_its_real_type(self) -> None:
        schema = _dictionary(OrganizationIncludesResponse.model_json_schema())
        locations = _dictionary(_dictionary(schema["properties"])["locations"])

        assert locations["anyOf"] == [
            {"items": {"$ref": "#/$defs/ContactLocationResponse"}, "type": "array"},
            {"type": "null"},
        ]

    def test_a_to_one_field_publishes_its_real_type(self) -> None:
        schema = _dictionary(PersonIncludesResponse.model_json_schema())
        company = _dictionary(_dictionary(schema["properties"])["company"])

        assert company["anyOf"] == [{"$ref": "#/$defs/CompanyRefResponse"}, {"type": "null"}]

    @pytest.mark.parametrize(
        "model",
        [OrganizationIncludesResponse, PersonIncludesResponse, ActivityIncludesResponse],
    )
    def test_the_metadata_itself_is_not_a_published_definition(
        self, model: type[BaseModel]
    ) -> None:
        assert "Include" not in _dictionary(_dictionary(model.model_json_schema())["$defs"])


class TestTheIncludesModelsPublishTheProjectedDescriptions:
    """Why the includes are typed models: a `dict[str, BaseModel]` field publishes a bare
    `$ref` to `BaseModel` and every one of these descriptions is lost from the output schema.
    """

    def test_the_organization_schema_reaches_a_named_projected_field(self) -> None:
        published = _defs_descriptions(OrganizationIncludesResponse)

        location_title = ContactLocationResponse.model_fields["location_title"].description
        assert location_title is not None
        assert location_title in published

    def test_the_organization_schema_carries_every_projected_description(self) -> None:
        published = _defs_descriptions(OrganizationIncludesResponse)

        assert (
            _field_descriptions(ContactLocationResponse)
            | _field_descriptions(ContactEmailResponse)
            | _field_descriptions(ContactCardResponse)
            | _field_descriptions(InternalOwnerResponse)
        ) <= published

    def test_the_person_schema_carries_every_projected_description(self) -> None:
        published = _defs_descriptions(PersonIncludesResponse)

        assert (
            _field_descriptions(ContactLocationResponse)
            | _field_descriptions(ContactEmailResponse)
            | _field_descriptions(CompanyRefResponse)
            | _field_descriptions(InternalOwnerResponse)
        ) <= published
