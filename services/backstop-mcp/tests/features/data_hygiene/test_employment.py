"""`EmploymentIndex` and its builders: one winner per `(person, organization)` pair.

Each test below is meant to read as a mini walkthrough:

1. **Configure the checks** — which relationship types count as employment / former
   employment (`EmploymentRules` / `TypeVocabulary`), same `configure_checks` as
   `test_departed.py`.
2. **Prepare the side-loaded record** — `entityRelationships` plus their types, via
   `helpers.person_org` / `helpers.relationship_types`.
3. **Run verification** — `build_person_employment_index` / `build_organization_employment_index`
   (what `EmploymentIndexFactory.index_for_person` / `index_for_organization` delegate to), then
   query `status` / `departure` / `pairs`.

Numbered classes below correspond to the nine cases in
`docs/plans/2026-08-05-employment-index-design.md`'s "Testing strategy".
"""

from datetime import date

from backstop_mcp.features.data_hygiene import DepartureSignal, EmploymentRules, TypeVocabulary
from backstop_mcp.features.data_hygiene.employment import (
    EmploymentIndex,
    build_organization_employment_index,
    build_person_employment_index,
)
from backstop_mcp.features.data_hygiene.types import EmploymentStatus
from tests.features.data_hygiene.helpers import (
    EMPLOYEE_MIRROR_TYPE,
    EMPLOYEE_TYPE,
    FORMER_MIRROR_TYPE,
    FORMER_TYPE,
    MANAGEMENT_COMPANY_TYPE,
    OWNS_ACCOUNT_TYPE,
    TYPE_NAMES,
    person_org,
    relationship_types,
)

TODAY = date(2026, 8, 5)

EMPTY_TYPE_IDS: frozenset[str] = frozenset()
DEFAULT_EMPLOYMENT_MARKERS: frozenset[str] = frozenset({"employ"})
DEFAULT_FORMER_MARKERS: frozenset[str] = frozenset({"former", "previous", "ex-", "no longer"})


def configure_checks(
    *,
    employment_type_ids: frozenset[str] = EMPTY_TYPE_IDS,
    employment_markers: frozenset[str] = DEFAULT_EMPLOYMENT_MARKERS,
    former_type_ids: frozenset[str] = EMPTY_TYPE_IDS,
    former_markers: frozenset[str] = DEFAULT_FORMER_MARKERS,
) -> EmploymentRules:
    """Build the vocabulary the index uses — same shape create_app injects."""
    return EmploymentRules(
        employment=TypeVocabulary(type_ids=employment_type_ids, name_markers=employment_markers),
        former=TypeVocabulary(type_ids=former_type_ids, name_markers=former_markers),
    )


def person_index(
    relationships: list[dict[str, object]],
    *,
    checks: EmploymentRules,
    types: list[dict[str, object]] | None = None,
    today: date = TODAY,
) -> EmploymentIndex:
    return build_person_employment_index(
        relationships=relationships,
        relationship_types=types if types is not None else relationship_types(*TYPE_NAMES),
        rules=checks,
        today=today,
    )


def organization_index(
    relationships: list[dict[str, object]],
    *,
    checks: EmploymentRules,
    types: list[dict[str, object]] | None = None,
    today: date = TODAY,
) -> EmploymentIndex:
    return build_organization_employment_index(
        relationships=relationships,
        relationship_types=types if types is not None else relationship_types(*TYPE_NAMES),
        rules=checks,
        today=today,
    )


class TestSameOrgConflictPersonSide:
    """Case 1/2 — person 341833933, org 341208613: the real ids from the design doc's Problem
    section, a genuine tenant record where one person carries both a live and an ended
    relationship to the same organization.
    """

    def test_a_later_current_type_beats_an_earlier_former_type(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org(
                "1",
                type_id=EMPLOYEE_TYPE,
                source_id="341833933",
                dest_id="341208613",
                created_timestamp="2022-01-01",
            ),
            person_org(
                "2",
                type_id=FORMER_TYPE,
                source_id="341833933",
                dest_id="341208613",
                created_timestamp="2021-01-01",
            ),
        ]

        index = person_index(relationships, checks=checks)

        assert (
            index.status(person_id="341833933", organization_id="341208613")
            is EmploymentStatus.CURRENT
        )
        assert index.departure(person_id="341833933", organization_id="341208613") is None

    def test_reversed_dates_flip_the_verdict_to_departed(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org(
                "1",
                type_id=EMPLOYEE_TYPE,
                source_id="341833933",
                dest_id="341208613",
                created_timestamp="2021-01-01",
            ),
            person_org(
                "2",
                type_id=FORMER_TYPE,
                source_id="341833933",
                dest_id="341208613",
                created_timestamp="2022-01-01",
            ),
        ]

        index = person_index(relationships, checks=checks)

        assert (
            index.status(person_id="341833933", organization_id="341208613")
            is EmploymentStatus.FORMER
        )
        departed = index.departure(person_id="341833933", organization_id="341208613")
        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE


class TestElapsedEndDateOnACurrentType:
    """Case 3/4 — rel 78305487: a `CURRENT`-typed relationship whose own `endDate` has already
    passed is rewritten to a departure dated at that `endDate`.
    """

    def test_an_elapsed_end_date_is_a_departure_with_the_end_date_signal(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org("78305487", type_id=EMPLOYEE_TYPE, end_date="2022-12-31"),
        ]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.FORMER
        departed = index.departure(person_id="p1", organization_id="o1")
        assert departed is not None
        assert departed.signal is DepartureSignal.END_DATE
        assert departed.end_date == "2022-12-31"

    def test_a_future_end_date_stays_current(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=EMPLOYEE_TYPE, end_date="2027-01-01")]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT
        assert index.departure(person_id="p1", organization_id="o1") is None


class TestStartDateBeatsCreatedTimestamp:
    """Case 5 — a current edge's own `startDate` predates its own `createdTimestamp` (the record
    was backfilled after the fact); a former edge dated between the two must still win, which only
    happens if the current edge's effective date is read from `startDate`, not `createdTimestamp`.
    """

    def test_the_former_edge_dated_between_them_wins(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org(
                "1",
                type_id=EMPLOYEE_TYPE,
                start_date="2020-01-01",
                created_timestamp="2023-01-01",
            ),
            person_org("2", type_id=FORMER_TYPE, created_timestamp="2021-06-01"),
        ]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.FORMER

    def test_without_a_start_date_the_same_former_edge_loses_to_created_timestamp(self) -> None:
        """Same former edge (2021-06-01) as the test above, but the current edge now carries only
        `createdTimestamp` (2023-01-01), no `startDate`. That later date is read as its effective
        date and outranks the former edge — proving the primary test's `FORMER` verdict really
        does depend on `startDate` (2020) being read in preference to `createdTimestamp` (2023),
        not on some other property of the fixture.
        """
        checks = configure_checks()
        relationships = [
            person_org("1", type_id=EMPLOYEE_TYPE, created_timestamp="2023-01-01"),
            person_org("2", type_id=FORMER_TYPE, created_timestamp="2021-06-01"),
        ]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT


class TestMultiOrg:
    """Case 6 — departed from A, current at B: both pairs are queryable independently, neither
    collapses into the other the way `detect_departed_employment`'s single verdict would.
    """

    def test_both_organizations_are_queryable_independently(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org("1", type_id=FORMER_TYPE, dest_id="orgA"),
            person_org("2", type_id=EMPLOYEE_TYPE, dest_id="orgB"),
        ]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="orgA") is EmploymentStatus.FORMER
        assert index.status(person_id="p1", organization_id="orgB") is EmploymentStatus.CURRENT
        departed_a = index.departure(person_id="p1", organization_id="orgA")
        assert departed_a is not None
        assert departed_a.organization_id == "orgA"
        assert index.departure(person_id="p1", organization_id="orgB") is None

    def test_pairs_lists_both_statuses_without_collapsing(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org("1", type_id=FORMER_TYPE, dest_id="orgA"),
            person_org("2", type_id=EMPLOYEE_TYPE, dest_id="orgB"),
        ]

        index = person_index(relationships, checks=checks)

        former_pairs = index.pairs(status=EmploymentStatus.FORMER)
        current_pairs = index.pairs(status=EmploymentStatus.CURRENT)
        assert len(former_pairs) == 1
        assert len(current_pairs) == 1


class TestOrganizationSideIndex:
    """Case 7 — an organization's own GET side-loads mirror types (different ids/names, reversed
    direction) that must classify identically to their person-side counterparts, while
    `owns account` / `management company of` — org-side types that are not employment at all —
    drop as `IRRELEVANT`.
    """

    def test_mirror_current_type_classifies_as_current(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org(
                "1",
                type_id=EMPLOYEE_MIRROR_TYPE,
                source_type="organizations",
                source_id="o1",
                dest_type="people",
                dest_id="p1",
            )
        ]
        types = relationship_types(EMPLOYEE_MIRROR_TYPE)

        index = organization_index(relationships, checks=checks, types=types)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT

    def test_mirror_former_type_classifies_as_departed(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org(
                "1",
                type_id=FORMER_MIRROR_TYPE,
                source_type="organizations",
                source_id="o1",
                dest_type="people",
                dest_id="p1",
            )
        ]
        types = relationship_types(FORMER_MIRROR_TYPE)

        index = organization_index(relationships, checks=checks, types=types)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.FORMER
        departed = index.departure(person_id="p1", organization_id="o1")
        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE

    def test_owns_account_and_management_company_of_drop_as_irrelevant(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org(
                "1",
                type_id=OWNS_ACCOUNT_TYPE,
                source_type="organizations",
                source_id="o1",
                dest_type="people",
                dest_id="p1",
            ),
            person_org(
                "2",
                type_id=MANAGEMENT_COMPANY_TYPE,
                source_type="organizations",
                source_id="o1",
                dest_type="people",
                dest_id="p1",
            ),
        ]
        types = relationship_types(OWNS_ACCOUNT_TYPE, MANAGEMENT_COMPANY_TYPE)

        index = organization_index(relationships, checks=checks, types=types)

        # No employment evidence at all for this pair: neither edge was admitted.
        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.IRRELEVANT
        assert index.departure(person_id="p1", organization_id="o1") is None


class TestBothBuildersAgree:
    """Case 8 — the same logical pair, fed through either payload shape (person's own GET vs.
    organization's own GET), must resolve to the same `EmploymentRecord`. `person_org`'s
    `source_type`/`dest_type` swap simulates the organization payload shape without a second
    builder, per its own docstring.
    """

    def test_a_departure_resolves_the_same_from_either_side(self) -> None:
        checks = configure_checks()
        person_side = [person_org("1", type_id=FORMER_TYPE, source_id="p1", dest_id="o1")]
        organization_side = [
            person_org(
                "1",
                type_id=FORMER_MIRROR_TYPE,
                source_type="organizations",
                source_id="o1",
                dest_type="people",
                dest_id="p1",
            )
        ]

        from_person = person_index(person_side, checks=checks)
        from_organization = organization_index(
            organization_side, checks=checks, types=relationship_types(FORMER_MIRROR_TYPE)
        )

        assert from_person.status(
            person_id="p1", organization_id="o1"
        ) == from_organization.status(person_id="p1", organization_id="o1")
        person_departed = from_person.departure(person_id="p1", organization_id="o1")
        org_departed = from_organization.departure(person_id="p1", organization_id="o1")
        assert person_departed is not None
        assert org_departed is not None
        assert person_departed.signal == org_departed.signal
        assert person_departed.organization_id == org_departed.organization_id


class TestMalformedInput:
    """Case 9 — every malformed shape the index is built from is dropped rather than raised."""

    def test_missing_resource_id_is_dropped(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE, dest_id=None)]

        index = person_index(relationships, checks=checks)

        # No identifiable organization: nothing to key the pair on, so nothing is indexed.
        assert index.pairs(status=EmploymentStatus.FORMER) == ()

    def test_unparseable_dates_fall_back_and_still_resolve(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org(
                "1",
                type_id=EMPLOYEE_TYPE,
                start_date="not-a-date",
                created_timestamp="also-not-a-date",
            )
        ]

        index = person_index(relationships, checks=checks)

        # No usable date anywhere on the edge: it still counts, as the sole edge for its pair.
        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT

    def test_unsideloaded_type_is_treated_as_untyped_and_stays_current(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE)]

        index = person_index(relationships, checks=checks, types=[])

        # The type resource never side-loaded, so `type_name` is None; `classify_employment`
        # reads that as no signal at all, i.e. CURRENT, never an invented departure.
        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT
        assert index.departure(person_id="p1", organization_id="o1") is None
