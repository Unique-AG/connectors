"""`include_plan`: what we ask Backstop for, and what we hand back."""

import logging
from typing import ClassVar, cast

import pytest
from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiResourceDocument
from backstop_mcp.features.includes import (
    ActivityIncludesResponse,
    ContactCardResponse,
    OrganizationInclude,
    OrganizationIncludesResponse,
    PersonIncludesResponse,
    include_plan,
)


class _Attrs(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow")

    name: str


def _organization(
    *,
    relationships: dict[str, object],
    included: list[dict[str, object]],
) -> BackstopApiResourceDocument[_Attrs]:
    return BackstopApiResourceDocument[_Attrs].model_validate(
        {
            "data": {
                "id": "341208613",
                "type": "organizations",
                "attributes": {"name": "Koch Investments Group"},
                "relationships": relationships,
            },
            "included": included,
        }
    )


def _location(resource_id: str, title: str) -> dict[str, object]:
    return {
        "type": "contact-locations",
        "id": resource_id,
        "attributes": {
            "locationTitle": title,
            "address": "18867 North Thompson Peak Parkway, Suite 250",
            "city": "Scottsdale",
            "cityResolvedName": "Scottsdale",
            "state": "AZ",
            "stateResolvedName": "AZ",
            "country": "United States of America",
            "countryResolvedName": "United States of America",
            "postalCode": "85255",
            "phoneNumber": "(480) 419-3625",
            "isPrimaryLocation": title == "Business",
            "primaryLocation": title == "Business",
            "fax": "",
        },
    }


class TestTheQueryParam:
    def test_translates_our_names_into_backstop_relationships(self) -> None:
        plan = include_plan(
            OrganizationIncludesResponse, requested=["locations", "email_addresses"]
        )

        assert plan.param == "contactLocations,contactEmails"

    def test_keeps_the_order_the_caller_asked_in(self) -> None:
        plan = include_plan(
            OrganizationIncludesResponse, requested=["representative", "primary_contact"]
        )

        assert plan.param == "representative,primaryContact"

    def test_asking_for_nothing_produces_nothing(self) -> None:
        """`get_person` joins this with its own include, so a leading comma would be a bad URL."""
        assert include_plan(PersonIncludesResponse, requested=[]).param == ""

    def test_a_repeated_name_is_asked_for_once(self) -> None:
        assert include_plan(PersonIncludesResponse, requested=["company", "company"]).param == (
            "company"
        )

    def test_the_person_model_exposes_its_own_names(self) -> None:
        plan = include_plan(PersonIncludesResponse, requested=["company", "locations"])

        assert plan.param == "company,contactLocations"

    def test_activity_history_always_asks_for_tags_and_attendees(self) -> None:
        plan = include_plan(
            ActivityIncludesResponse, requested=["activity_tags", "attendees"]
        )

        assert plan.param == "activityTags,attendees"

    def test_a_name_the_model_does_not_declare_is_an_internal_invariant(self) -> None:
        """Unreachable through the overloads — the cast is what a type error looks like at runtime.

        `include_plan(OrganizationIncludesResponse, requested=["activities"])` does not compile,
        and FastMCP rejects the name at the MCP boundary besides. The assert is the last line.
        """
        with pytest.raises(AssertionError, match="activities"):
            include_plan(
                OrganizationIncludesResponse,
                requested=cast(list[OrganizationInclude], ["activities"]),
            )

    def test_the_failure_names_the_model_that_defines_the_valid_set(self) -> None:
        """A person include on the organization model: also a compile error via the overloads."""
        with pytest.raises(AssertionError, match="OrganizationIncludesResponse"):
            include_plan(
                OrganizationIncludesResponse,
                requested=cast(list[OrganizationInclude], ["company"]),
            )


class TestProjectToMany:
    def test_projects_every_side_loaded_location(self) -> None:
        document = _organization(
            relationships={
                "contactLocations": {
                    "data": [
                        {"type": "contact-locations", "id": "loc-1"},
                        {"type": "contact-locations", "id": "loc-2"},
                    ]
                }
            },
            included=[_location("loc-1", "Business"), _location("loc-2", "Home")],
        )

        included = include_plan(OrganizationIncludesResponse, requested=["locations"]).project(
            document=document
        )

        locations = included.locations
        assert locations is not None
        assert [location.location_title for location in locations] == ["Business", "Home"]

    def test_the_duplicate_source_fields_collapse_to_one_projected_field(self) -> None:
        document = _organization(
            relationships={
                "contactLocations": {"data": [{"type": "contact-locations", "id": "loc-1"}]}
            },
            included=[_location("loc-1", "Business")],
        )

        included = include_plan(OrganizationIncludesResponse, requested=["locations"]).project(
            document=document
        )

        locations = included.locations
        assert locations is not None
        assert locations[0].model_dump() == {
            "id": "loc-1",
            "location_title": "Business",
            "address": "18867 North Thompson Peak Parkway, Suite 250",
            "city": "Scottsdale",
            "state": "AZ",
            "country": "United States of America",
            "postal_code": "85255",
            "phone": "(480) 419-3625",
            "is_primary": True,
        }

    def test_requested_with_no_data_is_empty_and_not_requested_is_none(self) -> None:
        """`[]` means we looked and there are none; `None` means we did not look."""
        document = _organization(
            relationships={
                "contactLocations": {"data": [{"type": "contact-locations", "id": "loc-1"}]}
            },
            included=[_location("loc-1", "Business")],
        )

        included = include_plan(
            OrganizationIncludesResponse, requested=["email_addresses"]
        ).project(document=document)

        assert included.email_addresses == []
        assert included.locations is None

    def test_a_retired_address_is_returned_and_flagged(self) -> None:
        document = _organization(
            relationships={
                "contactEmails": {
                    "data": [
                        {"type": "contact-emails", "id": "e1"},
                        {"type": "contact-emails", "id": "e2"},
                    ]
                }
            },
            included=[
                {
                    "type": "contact-emails",
                    "id": "e1",
                    "attributes": {
                        "sortOrder": 0,
                        "retired": True,
                        "email": "kent.voss@kochind.com",
                    },
                },
                {
                    "type": "contact-emails",
                    "id": "e2",
                    "attributes": {
                        "sortOrder": 0,
                        "retired": False,
                        "email": "vossk@kochinvests.com",
                    },
                },
            ],
        )

        included = include_plan(
            OrganizationIncludesResponse, requested=["email_addresses"]
        ).project(document=document)

        emails = included.email_addresses
        assert emails is not None
        assert [(email.email, email.retired) for email in emails] == [
            ("kent.voss@kochind.com", True),
            ("vossk@kochinvests.com", False),
        ]


class TestProjectToOne:
    def test_projects_the_primary_contact_to_a_contact_card(self) -> None:
        document = _organization(
            relationships={"primaryContact": {"data": {"type": "people", "id": "p1"}}},
            included=[
                {
                    "type": "people",
                    "id": "p1",
                    "attributes": {
                        "name": "Voss, Kent",
                        "jobTitle": "Managing Director, Research",
                        "email": "vossk@kochinvests.com",
                        "phone": "(480) 419-3625",
                        "companyName": "Koch Investments Group",
                        "streetAddress": "18867 North Thompson Peak Parkway",
                        "regularCustomFieldValues": {"1": "noise"},
                    },
                }
            ],
        )

        included = include_plan(
            OrganizationIncludesResponse, requested=["primary_contact"]
        ).project(document=document)

        card = included.primary_contact
        assert card is not None
        assert card.model_dump() == {
            "id": "p1",
            "name": "Voss, Kent",
            "job_title": "Managing Director, Research",
            "email": "vossk@kochinvests.com",
            "phone": "(480) 419-3625",
            "company_name": "Koch Investments Group",
        }

    def test_projects_the_representative_to_our_internal_owner(self) -> None:
        document = _organization(
            relationships={"representative": {"data": {"type": "system-users", "id": "u1"}}},
            included=[
                {
                    "type": "system-users",
                    "id": "u1",
                    "attributes": {
                        "name": "Margaret Lucas",
                        "userName": "mlucas",
                        "email": "margaret.lucas@capstoneco.com",
                        "phoneNumber": "12122321462",
                        "isBsgAdmin": False,
                    },
                }
            ],
        )

        included = include_plan(OrganizationIncludesResponse, requested=["representative"]).project(
            document=document
        )

        owner = included.representative
        assert owner is not None
        assert owner.model_dump() == {
            "id": "u1",
            "name": "Margaret Lucas",
            "user_name": "mlucas",
            "email": "margaret.lucas@capstoneco.com",
            "phone": "12122321462",
        }

    def test_a_to_one_include_pointing_at_nothing_is_none(self) -> None:
        document = _organization(relationships={}, included=[])

        included = include_plan(PersonIncludesResponse, requested=["company"]).project(
            document=document
        )

        assert included.company is None


class TestAProjectionCarriesTheRecordsOwnId:
    """Without it a projection is a dead end: the tools it points at refuse a guessed id."""

    def test_the_primary_contact_carries_the_people_id_get_person_takes(self) -> None:
        document = _organization(
            relationships={"primaryContact": {"data": {"type": "people", "id": "341688185"}}},
            included=[{"type": "people", "id": "341688185", "attributes": {"name": "Voss, Kent"}}],
        )

        included = include_plan(
            OrganizationIncludesResponse, requested=["primary_contact"]
        ).project(document=document)

        card = included.primary_contact
        assert card is not None
        assert card.id == "341688185"

    def test_the_company_carries_the_organizations_id_get_organization_takes(self) -> None:
        document = _organization(
            relationships={"company": {"data": {"type": "organizations", "id": "341208613"}}},
            included=[
                {
                    "type": "organizations",
                    "id": "341208613",
                    "attributes": {"name": "Koch Investments Group"},
                }
            ],
        )

        included = include_plan(PersonIncludesResponse, requested=["company"]).project(
            document=document
        )

        company = included.company
        assert company is not None
        assert company.id == "341208613"

    def test_the_resource_id_wins_over_an_id_inside_attributes(self) -> None:
        """Backstop puts foreign keys in `attributes`; the resource's own identity is above it."""
        document = _organization(
            relationships={"primaryContact": {"data": {"type": "people", "id": "p1"}}},
            included=[
                {
                    "type": "people",
                    "id": "p1",
                    "attributes": {"id": "some-foreign-key", "name": "Voss, Kent"},
                }
            ],
        )

        included = include_plan(
            OrganizationIncludesResponse, requested=["primary_contact"]
        ).project(document=document)

        card = included.primary_contact
        assert card is not None
        assert card.id == "p1"

    def test_each_side_loaded_row_keeps_its_own_id(self) -> None:
        document = _organization(
            relationships={
                "contactLocations": {
                    "data": [
                        {"type": "contact-locations", "id": "loc-1"},
                        {"type": "contact-locations", "id": "loc-2"},
                    ]
                }
            },
            included=[_location("loc-1", "Business"), _location("loc-2", "Home")],
        )

        included = include_plan(OrganizationIncludesResponse, requested=["locations"]).project(
            document=document
        )

        locations = included.locations
        assert locations is not None
        assert [location.id for location in locations] == ["loc-1", "loc-2"]


class TestAMalformedSideLoadIsDroppedNotFatal:
    def test_one_unreadable_location_does_not_lose_the_other(self) -> None:
        document = _organization(
            relationships={
                "contactLocations": {
                    "data": [
                        {"type": "contact-locations", "id": "loc-1"},
                        {"type": "contact-locations", "id": "loc-2"},
                    ]
                }
            },
            included=[
                {"type": "contact-locations", "id": "loc-1", "attributes": "not an object"},
                _location("loc-2", "Home"),
            ],
        )

        included = include_plan(OrganizationIncludesResponse, requested=["locations"]).project(
            document=document
        )

        locations = included.locations
        assert locations is not None
        assert [location.location_title for location in locations] == ["Home"]

    def test_the_drop_is_warned_about(self, caplog: pytest.LogCaptureFixture) -> None:
        document = _organization(
            relationships={"contactEmails": {"data": [{"type": "contact-emails", "id": "e1"}]}},
            included=[
                {
                    "type": "contact-emails",
                    "id": "e1",
                    "attributes": {"email": "no-retired-flag@example.com"},
                }
            ],
        )

        with caplog.at_level(logging.WARNING):
            included = include_plan(
                OrganizationIncludesResponse, requested=["email_addresses"]
            ).project(document=document)

        assert included.email_addresses == []
        assert [record.message for record in caplog.records] == ["includes.side_load.unreadable"]


class TestASideLoadOfTheWrongTypeIsDropped:
    """The field's `Include` names the type its relationship returns; anything else is not it."""

    def test_a_resource_under_another_type_does_not_reach_the_caller(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The organization validates as a `ContactLocationResponse`; only its type catches it."""
        document = _organization(
            relationships={
                "contactLocations": {
                    "data": [
                        {"type": "organizations", "id": "org-1"},
                        {"type": "contact-locations", "id": "loc-2"},
                    ]
                }
            },
            included=[
                {
                    "type": "organizations",
                    "id": "org-1",
                    "attributes": {"locationTitle": "Koch Investments Group"},
                },
                _location("loc-2", "Home"),
            ],
        )

        with caplog.at_level(logging.WARNING):
            included = include_plan(OrganizationIncludesResponse, requested=["locations"]).project(
                document=document
            )

        locations = included.locations
        assert locations is not None
        assert [location.location_title for location in locations] == ["Home"]
        assert [record.message for record in caplog.records] == [
            "includes.side_load.unexpected_type"
        ]

    def test_a_to_one_include_whose_only_resource_is_dropped_is_none(self) -> None:
        document = _organization(
            relationships={"representative": {"data": {"type": "people", "id": "p1"}}},
            included=[{"type": "people", "id": "p1", "attributes": {"name": "Voss, Kent"}}],
        )

        included = include_plan(OrganizationIncludesResponse, requested=["representative"]).project(
            document=document
        )

        assert included.representative is None


class TestALinkageThatResolvesToNothing:
    """Distinct from an empty relationship, and the likeliest cause is a forgotten `?include=`."""

    def test_linked_ids_with_nothing_side_loaded_are_warned_about(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        document = _organization(
            relationships={
                "contactLocations": {"data": [{"type": "contact-locations", "id": "loc-1"}]}
            },
            included=[],
        )

        with caplog.at_level(logging.WARNING):
            included = include_plan(OrganizationIncludesResponse, requested=["locations"]).project(
                document=document
            )

        assert included.locations == []
        assert [record.message for record in caplog.records] == ["includes.side_load.unresolved"]

    def test_a_relationship_with_no_linkage_is_not_warned_about(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Nothing linked is an answer we can stand behind, not a gap in what we fetched."""
        document = _organization(relationships={}, included=[])

        with caplog.at_level(logging.WARNING):
            include_plan(OrganizationIncludesResponse, requested=["locations"]).project(
                document=document
            )

        assert caplog.records == []


class TestAPlanAnswersInTheModelItWasBuiltFrom:
    """The query value and the projection come from one model, so they cannot be mismatched."""

    def test_a_plan_built_from_the_organization_model_answers_in_it(self) -> None:
        document = _organization(
            relationships={"primaryContact": {"data": {"type": "people", "id": "p1"}}},
            included=[{"type": "people", "id": "p1", "attributes": {"name": "Voss, Kent"}}],
        )

        included = include_plan(
            OrganizationIncludesResponse, requested=["primary_contact"]
        ).project(document=document)

        assert isinstance(included, OrganizationIncludesResponse)
        assert included.primary_contact == ContactCardResponse(id="p1", name="Voss, Kent")

    def test_a_plan_built_from_the_person_model_answers_in_it(self) -> None:
        document = _organization(
            relationships={"company": {"data": {"type": "organizations", "id": "o1"}}},
            included=[
                {
                    "type": "organizations",
                    "id": "o1",
                    "attributes": {"name": "Koch Investments Group"},
                }
            ],
        )

        included = include_plan(PersonIncludesResponse, requested=["company"]).project(
            document=document
        )

        assert isinstance(included, PersonIncludesResponse)
        assert included.company is not None
        assert included.company.name == "Koch Investments Group"
