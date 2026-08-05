"""The scan and its type classifier, with every collaborator passed explicitly.

Each test below is meant to read as a mini walkthrough:

1. **Configure the checks** — which relationship types count as employment / former
   employment (`DepartureRules` / `TypeVocabulary`).
2. **Prepare the side-loaded record** — `entityRelationships` plus their types.
3. **Run verification** — `detect_departed_employment` (what `DepartedContactDetector.verify`
   delegates to) or `classify_employment` for a single type.

The type names are the ones a real instance uses: `is employee of` and `is a former employee of`
against the same organization, plus `has portal access to` as a person→org link that is not
employment at all. The detector that assembles this from configuration is in `test_service.py`.
"""

from datetime import date

import pytest

from backstop_mcp.features.data_hygiene import (
    DepartedEmployment,
    DepartureRules,
    DepartureSignal,
    TypeVocabulary,
)
from backstop_mcp.features.data_hygiene.departed import (
    classify_employment,
    detect_departed_employment,
)
from backstop_mcp.features.data_hygiene.types import EmploymentStatus

TODAY = date(2026, 8, 5)

EMPLOYEE_TYPE = "456439"
FORMER_TYPE = "459795"
PORTAL_TYPE = "633147"

TYPE_NAMES = {
    EMPLOYEE_TYPE: "is employee of",
    FORMER_TYPE: "is a former employee of",
    PORTAL_TYPE: "has portal access to",
}

# Defaults mirror BackstopConfig: employment marker "employ", former markers
# "former" / "previous" / "ex-" / "no longer", no hard-coded type ids.
EMPTY_TYPE_IDS: frozenset[str] = frozenset()
DEFAULT_EMPLOYMENT_MARKERS: frozenset[str] = frozenset({"employ"})
DEFAULT_FORMER_MARKERS: frozenset[str] = frozenset({"former", "previous", "ex-", "no longer"})


def configure_checks(
    *,
    employment_type_ids: frozenset[str] = EMPTY_TYPE_IDS,
    employment_markers: frozenset[str] = DEFAULT_EMPLOYMENT_MARKERS,
    former_type_ids: frozenset[str] = EMPTY_TYPE_IDS,
    former_markers: frozenset[str] = DEFAULT_FORMER_MARKERS,
) -> DepartureRules:
    """Build the vocabulary the scan uses — same shape create_app injects."""
    return DepartureRules(
        employment=TypeVocabulary(type_ids=employment_type_ids, name_markers=employment_markers),
        former=TypeVocabulary(type_ids=former_type_ids, name_markers=former_markers),
    )


def relationship_types(*type_ids: str) -> list[dict[str, object]]:
    """Side-loaded `entity-relationship-types` resources (id → name)."""
    return [
        {
            "type": "entity-relationship-types",
            "id": type_id,
            "attributes": {"name": TYPE_NAMES[type_id]},
        }
        for type_id in type_ids
    ]


def person_org(
    er_id: str,
    *,
    end_date: str | None = None,
    source_type: str = "people",
    source_id: str = "p1",
    dest_type: str = "organizations",
    dest_id: str = "o1",
    type_id: str | None = EMPLOYEE_TYPE,
) -> dict[str, object]:
    """One `entityRelationships` resource linking a person side to an org side."""
    attributes: dict[str, object] = {
        "sourceEntity": {"resourceId": source_id, "resourceType": source_type},
        "destinationEntity": {"resourceId": dest_id, "resourceType": dest_type},
    }
    if end_date is not None:
        attributes["endDate"] = end_date
    relationships: dict[str, object] = {}
    if type_id is not None:
        relationships["entityRelationshipType"] = {
            "data": {"type": "entity-relationship-types", "id": type_id}
        }
    return {
        "type": "entity-relationships",
        "id": er_id,
        "attributes": attributes,
        "relationships": relationships,
    }


def verify(
    relationships: list[dict[str, object]],
    *,
    checks: DepartureRules,
    types: list[dict[str, object]] | None = None,
    today: date = TODAY,
) -> DepartedEmployment | None:
    """Run the pure scan — same call `DepartedContactDetector.verify` makes."""
    return detect_departed_employment(
        relationships=relationships,
        relationship_types=types if types is not None else relationship_types(*TYPE_NAMES),
        rules=checks,
        today=today,
    )


class TestFormerRelationshipType:
    """The signal that does the work: tenants model a departure as a different type."""

    def test_former_employee_type_is_a_departure(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE)]

        departed = verify(relationships, checks=checks)

        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE
        assert departed.organization_id == "o1"
        assert departed.organization_type == "organizations"
        assert departed.relationship_type_id == FORMER_TYPE
        assert departed.relationship_type_name == "is a former employee of"
        # No date was recorded; the type alone carried the signal.
        assert departed.end_date is None

    def test_current_employee_type_is_not(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=EMPLOYEE_TYPE)]

        assert verify(relationships, checks=checks) is None

    def test_former_wins_over_the_employment_marker_it_contains(self) -> None:
        """`is a former employee of` contains `employee`; employment-first would clear it."""
        checks = configure_checks(employment_markers=frozenset({"employee"}))
        relationships = [person_org("1", type_id=FORMER_TYPE)]

        departed = verify(relationships, checks=checks)

        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE

    def test_configured_ids_match_without_any_name(self) -> None:
        checks = configure_checks(
            former_type_ids=frozenset({FORMER_TYPE}),
            former_markers=frozenset(),
        )
        relationships = [person_org("1", type_id=FORMER_TYPE)]
        # No type names side-loaded — only the configured id can match.
        types: list[dict[str, object]] = []

        departed = verify(relationships, checks=checks, types=types)

        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE

    def test_a_former_type_with_a_date_reports_both(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE, end_date="2022-12-31")]

        departed = verify(relationships, checks=checks)

        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE
        assert departed.end_date == "2022-12-31"

    def test_no_former_vocabulary_leaves_only_end_date(self) -> None:
        checks = configure_checks(former_markers=frozenset())
        former_only = [person_org("1", type_id=FORMER_TYPE)]
        former_with_date = [person_org("1", type_id=FORMER_TYPE, end_date="2020-01-01")]

        assert verify(former_only, checks=checks) is None
        assert verify(former_with_date, checks=checks) is not None


class TestCurrentOutranksFormer:
    """One live relationship beats any number of ended ones, whatever the array order."""

    def test_current_and_former_at_the_same_org_is_not_departed(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org("1", type_id=FORMER_TYPE),
            person_org("2", type_id=EMPLOYEE_TYPE),
        ]

        assert verify(relationships, checks=checks) is None

    def test_verdict_does_not_depend_on_order(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org("2", type_id=EMPLOYEE_TYPE),
            person_org("1", type_id=FORMER_TYPE),
        ]

        assert verify(relationships, checks=checks) is None

    def test_current_elsewhere_does_not_clear_a_departure(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org("1", type_id=FORMER_TYPE, dest_id="o1"),
            person_org("2", type_id=EMPLOYEE_TYPE, dest_id="o2"),
        ]

        departed = verify(relationships, checks=checks)

        assert departed is not None
        assert departed.organization_id == "o1"

    def test_portal_access_cannot_vouch_for_a_departed_person(self) -> None:
        """`has portal access to` is person→org but not employment: it must not clear."""
        checks = configure_checks()
        relationships = [
            person_org("1", type_id=FORMER_TYPE),
            person_org("2", type_id=PORTAL_TYPE),
        ]

        departed = verify(relationships, checks=checks)

        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE

    def test_portal_access_alone_is_not_a_departure_either(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=PORTAL_TYPE, end_date="2020-01-01")]

        assert verify(relationships, checks=checks) is None


class TestEndDate:
    def test_past_end_date_is_a_departure(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", end_date="2022-12-31T00:00:00.000-0500")]

        departed = verify(relationships, checks=checks)

        assert departed is not None
        assert departed.signal is DepartureSignal.END_DATE
        # Normalised: the CRM writes a full timestamp for what the API documents as a date.
        assert departed.end_date == "2022-12-31"

    def test_future_end_date_is_not(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", end_date="2027-01-01")]

        assert verify(relationships, checks=checks) is None

    def test_today_is_not_yet_departed(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", end_date=TODAY.isoformat())]

        assert verify(relationships, checks=checks) is None

    def test_unparseable_end_date_is_ignored(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", end_date="not-a-date")]

        assert verify(relationships, checks=checks) is None

    def test_an_ended_relationship_does_not_clear_a_former_one(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org("1", type_id=FORMER_TYPE),
            person_org("2", end_date="2020-01-01"),
        ]

        departed = verify(relationships, checks=checks)

        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE


class TestPersonToOrgGate:
    def test_reversed_sides_still_match(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org(
                "1",
                type_id=FORMER_TYPE,
                source_type="organizations",
                source_id="o9",
                dest_type="people",
                dest_id="p1",
            )
        ]

        departed = verify(relationships, checks=checks)

        assert departed is not None
        assert departed.organization_id == "o9"

    def test_contacts_count_as_person_side(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE, source_type="contacts")]

        assert verify(relationships, checks=checks) is not None

    def test_non_org_destination_is_skipped(self) -> None:
        """A person→fund-product link is not employment however its type is named."""
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE, dest_type="hedge-fund-products")]

        assert verify(relationships, checks=checks) is None

    def test_person_to_person_link_is_skipped(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE, dest_type="people")]

        assert verify(relationships, checks=checks) is None

    def test_missing_side_is_skipped(self) -> None:
        checks = configure_checks()
        relationships: list[dict[str, object]] = [
            {
                "type": "entity-relationships",
                "id": "1",
                "attributes": {
                    "sourceEntity": {"resourceId": "p1", "resourceType": "people"},
                },
                "relationships": {
                    "entityRelationshipType": {
                        "data": {"type": "entity-relationship-types", "id": FORMER_TYPE}
                    }
                },
            }
        ]

        assert verify(relationships, checks=checks) is None


class TestMalformedInput:
    def test_no_relationships_at_all(self) -> None:
        checks = configure_checks()

        assert verify([], checks=checks) is None

    def test_unreadable_relationship_is_skipped(self) -> None:
        checks = configure_checks()
        relationships: list[dict[str, object]] = [
            {"type": "entity-relationships", "attributes": {}}
        ]

        assert verify(relationships, checks=checks) is None

    def test_untyped_relationship_neither_departs_nor_crashes(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=None)]

        assert verify(relationships, checks=checks) is None

    def test_untyped_relationship_keeps_its_end_date(self) -> None:
        """The fallback: with no type to judge, `endDate` is the only evidence left."""
        checks = configure_checks()
        relationships = [person_org("1", type_id=None, end_date="2020-01-01")]

        departed = verify(relationships, checks=checks)

        assert departed is not None
        assert departed.signal is DepartureSignal.END_DATE
        assert departed.relationship_type_name is None

    def test_type_that_did_not_side_load_is_treated_as_untyped(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE)]
        types: list[dict[str, object]] = []

        assert verify(relationships, checks=checks, types=types) is None

    def test_unnamed_type_is_dropped(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE)]
        types: list[dict[str, object]] = [
            {"type": "entity-relationship-types", "id": FORMER_TYPE, "attributes": {}}
        ]

        assert verify(relationships, checks=checks, types=types) is None


class TestClassifyEmployment:
    """Single-type classification the scan calls for each person→org relationship."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("is employee of", EmploymentStatus.CURRENT),
            ("is a former employee of", EmploymentStatus.FORMER),
            ("has portal access to", EmploymentStatus.IRRELEVANT),
        ],
    )
    def test_the_vocabulary_a_real_instance_uses(
        self, name: str, expected: EmploymentStatus
    ) -> None:
        checks = configure_checks(
            employment_markers=frozenset({"employ"}),
            former_markers=frozenset({"former"}),
        )

        status = classify_employment(type_id="9", type_name=name, rules=checks)

        assert status is expected

    def test_former_is_tested_before_employment(self) -> None:
        """Both markers match `is a former employee of`; the departure one has to win."""
        checks = configure_checks(
            employment_markers=frozenset({"employee"}),
            former_markers=frozenset({"former"}),
        )

        status = classify_employment(type_id="9", type_name="is a former employee of", rules=checks)

        assert status is EmploymentStatus.FORMER

    def test_configured_ids_decide_without_a_name(self) -> None:
        checks = configure_checks(
            employment_markers=frozenset({"employ"}),
            former_type_ids=frozenset({"459795"}),
            former_markers=frozenset(),
        )

        status = classify_employment(type_id="459795", type_name=None, rules=checks)

        assert status is EmploymentStatus.FORMER

    def test_no_type_signal_falls_back_to_current(self) -> None:
        """With nothing to judge, the person→org gate is the only evidence — never invent a
        departure, and keep `endDate` in play."""
        checks = configure_checks(
            employment_markers=frozenset({"employ"}),
            former_markers=frozenset({"former"}),
        )

        status = classify_employment(type_id=None, type_name=None, rules=checks)

        assert status is EmploymentStatus.CURRENT

    def test_an_id_whose_type_did_not_side_load_is_also_no_signal(self) -> None:
        """Same fallback as a record with no type at all — not a positive `IRRELEVANT` finding,
        which would drop the record and lose its `endDate`."""
        checks = configure_checks(
            employment_markers=frozenset({"employ"}),
            former_markers=frozenset({"former"}),
        )

        status = classify_employment(type_id="9", type_name=None, rules=checks)

        assert status is EmploymentStatus.CURRENT

    def test_empty_employment_vocabulary_admits_every_person_to_org_type(self) -> None:
        checks = configure_checks(
            employment_markers=frozenset(),
            former_markers=frozenset({"former"}),
        )

        status = classify_employment(type_id="9", type_name="has portal access to", rules=checks)

        assert status is EmploymentStatus.CURRENT

    def test_markers_are_case_insensitive(self) -> None:
        checks = configure_checks(
            employment_markers=frozenset({"employ"}),
            former_markers=frozenset({"former"}),
        )

        status = classify_employment(type_id="9", type_name="Is A Former Employee Of", rules=checks)

        assert status is EmploymentStatus.FORMER
