"""`EmploymentIndex` and its builders: one winner per `(person, organization)` pair, plus the
type classification (`classify_employment`) and edge-parsing machinery (`_employment_edges` and
its helpers) they rest on.

Each test below is meant to read as a mini walkthrough:

1. **Configure the checks** — which relationship types count as employment / former
   employment (`EmploymentRules` / `TypeVocabulary`).
2. **Prepare the side-loaded record** — `entityRelationships` plus their types, via
   `helpers.person_org` / `helpers.relationship_types`.
3. **Run verification** — `build_person_employment_index` / `build_organization_employment_index`
   (what `EmploymentIndexFactory.index_for_person` / `index_for_organization` delegate to), then
   query `status` / `departure` / `pairs` — or `classify_employment` directly for a single type.

Numbered classes below correspond to the nine cases in
`docs/plans/2026-08-05-employment-index-design.md`'s "Testing strategy". The remaining classes
cover the parsing/gate/malformed-input edge cases of `_employment_edges` and `classify_employment`
that predate `EmploymentIndex` and are unaffected by its single-winner-per-pair fold.
"""

from datetime import date

import pytest

from backstop_mcp.features.data_hygiene import DepartureSignal, EmploymentRules, TypeVocabulary
from backstop_mcp.features.data_hygiene.employment import (
    EmploymentIndex,
    build_organization_employment_index,
    build_person_employment_index,
    classify_employment,
)
from backstop_mcp.features.data_hygiene.types import EmploymentStatus
from tests.features.data_hygiene.helpers import (
    EMPLOYEE_MIRROR_TYPE,
    EMPLOYEE_TYPE,
    FORMER_MIRROR_TYPE,
    FORMER_TYPE,
    MANAGEMENT_COMPANY_TYPE,
    OWNS_ACCOUNT_TYPE,
    PORTAL_TYPE,
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


class TestTwoFormerEdgesForTheSamePair:
    """Two edges that both resolve to `FORMER` for one pair — a `FORMER_TYPE` record with no
    date, and a `CURRENT`-typed record whose elapsed `endDate` rewrites it to `END_DATE` — still
    need one winning `departure` to report. `EmploymentIndex` picks by date alone (any dated edge
    outranks an undated one, regardless of which signal it carries), which differs from the old
    `detect_departed_employment`'s signal-strength rule (`FORMER_TYPE` always won). Both edges
    agree on `status`, so only `departure`'s exact evidence tells the two rules apart.
    """

    def test_the_dated_edge_wins_the_departure_evidence_even_over_an_undated_former_type(
        self,
    ) -> None:
        checks = configure_checks()
        relationships = [
            person_org("1", type_id=FORMER_TYPE, dest_id="oA"),
            person_org("2", type_id=EMPLOYEE_TYPE, dest_id="oA", end_date="2020-01-01"),
        ]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="oA") is EmploymentStatus.FORMER
        departed = index.departure(person_id="p1", organization_id="oA")
        assert departed is not None
        assert departed.signal is DepartureSignal.END_DATE
        assert departed.end_date == "2020-01-01"


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
    collapses into the other the way a single-verdict-per-person scan would.
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

    def test_no_relationships_at_all(self) -> None:
        checks = configure_checks()

        index = person_index([], checks=checks)

        assert index.pairs(status=EmploymentStatus.FORMER) == ()
        assert index.pairs(status=EmploymentStatus.CURRENT) == ()

    def test_unreadable_relationship_is_skipped(self) -> None:
        checks = configure_checks()
        relationships: list[dict[str, object]] = [
            {"type": "entity-relationships", "attributes": {}}
        ]

        index = person_index(relationships, checks=checks)

        assert index.pairs(status=EmploymentStatus.FORMER) == ()
        assert index.pairs(status=EmploymentStatus.CURRENT) == ()

    def test_untyped_relationship_neither_departs_nor_crashes(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=None)]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT

    def test_untyped_relationship_keeps_its_end_date(self) -> None:
        """The fallback: with no type to judge, `endDate` is the only evidence left."""
        checks = configure_checks()
        relationships = [person_org("1", type_id=None, end_date="2020-01-01")]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.FORMER
        departed = index.departure(person_id="p1", organization_id="o1")
        assert departed is not None
        assert departed.signal is DepartureSignal.END_DATE
        assert departed.relationship_type_name is None

    def test_unnamed_type_is_dropped(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE)]
        types: list[dict[str, object]] = [
            {"type": "entity-relationship-types", "id": FORMER_TYPE, "attributes": {}}
        ]

        index = person_index(relationships, checks=checks, types=types)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT

    def test_unreadable_type_resource_is_dropped(self) -> None:
        """No id to key the name under, so the relationship is left with no type signal."""
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE)]
        types: list[dict[str, object]] = [
            {"type": "entity-relationship-types", "attributes": {"name": TYPE_NAMES[FORMER_TYPE]}}
        ]

        index = person_index(relationships, checks=checks, types=types)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT


class TestFormerRelationshipType:
    """The signal that does the work: tenants model a departure as a different type."""

    def test_former_employee_type_is_a_departure(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE)]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.FORMER
        departed = index.departure(person_id="p1", organization_id="o1")
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

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT
        assert index.departure(person_id="p1", organization_id="o1") is None

    def test_former_wins_over_the_employment_marker_it_contains(self) -> None:
        """`is a former employee of` contains `employee`; employment-first would clear it."""
        checks = configure_checks(employment_markers=frozenset({"employee"}))
        relationships = [person_org("1", type_id=FORMER_TYPE)]

        index = person_index(relationships, checks=checks)

        departed = index.departure(person_id="p1", organization_id="o1")
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

        index = person_index(relationships, checks=checks, types=types)

        departed = index.departure(person_id="p1", organization_id="o1")
        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE

    def test_a_former_type_with_a_date_reports_both(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE, end_date="2022-12-31")]

        index = person_index(relationships, checks=checks)

        departed = index.departure(person_id="p1", organization_id="o1")
        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE
        assert departed.end_date == "2022-12-31"

    def test_no_former_vocabulary_leaves_only_end_date(self) -> None:
        checks = configure_checks(former_markers=frozenset())
        former_only = [person_org("1", type_id=FORMER_TYPE)]
        former_with_date = [person_org("1", type_id=FORMER_TYPE, end_date="2020-01-01")]

        assert (
            person_index(former_only, checks=checks).status(person_id="p1", organization_id="o1")
            is EmploymentStatus.CURRENT
        )
        assert (
            person_index(former_with_date, checks=checks).status(
                person_id="p1", organization_id="o1"
            )
            is EmploymentStatus.FORMER
        )


class TestPortalAccessIsNotEmployment:
    """`has portal access to` is person→org but not employment: it must not vouch for, nor stand
    in for, an ended employment at the same organization.
    """

    def test_portal_access_cannot_vouch_for_a_departed_person(self) -> None:
        checks = configure_checks()
        relationships = [
            person_org("1", type_id=FORMER_TYPE),
            person_org("2", type_id=PORTAL_TYPE),
        ]

        index = person_index(relationships, checks=checks)

        departed = index.departure(person_id="p1", organization_id="o1")
        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE

    def test_portal_access_alone_is_not_a_departure_either(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=PORTAL_TYPE, end_date="2020-01-01")]

        index = person_index(relationships, checks=checks)

        # `has portal access to` classifies IRRELEVANT, so the edge is dropped before it ever
        # reaches an end-date check: no evidence for the pair at all, not a cleared departure.
        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.IRRELEVANT


class TestEndDateParsing:
    """`endDate` shapes an instance can send, on an otherwise-current relationship."""

    def test_past_end_date_is_a_departure(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", end_date="2022-12-31T00:00:00.000-0500")]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.FORMER
        departed = index.departure(person_id="p1", organization_id="o1")
        assert departed is not None
        assert departed.signal is DepartureSignal.END_DATE
        # Normalised: the CRM writes a full timestamp for what the API documents as a date.
        assert departed.end_date == "2022-12-31"

    def test_future_end_date_is_not(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", end_date="2027-01-01")]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT

    def test_today_is_not_yet_departed(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", end_date=TODAY.isoformat())]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT

    def test_unparseable_end_date_is_ignored(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", end_date="not-a-date")]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT

    def test_blank_end_date_is_ignored(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", end_date="   ")]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.CURRENT

    def test_a_compact_timestamp_still_parses(self) -> None:
        """Not the shape this instance writes, but its date part isn't the leading ten chars."""
        checks = configure_checks()
        relationships = [person_org("1", end_date="20221231T101530")]

        index = person_index(relationships, checks=checks)

        departed = index.departure(person_id="p1", organization_id="o1")
        assert departed is not None
        assert departed.end_date == "2022-12-31"


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

        index = person_index(relationships, checks=checks)

        departed = index.departure(person_id="p1", organization_id="o9")
        assert departed is not None
        assert departed.organization_id == "o9"

    def test_contacts_count_as_person_side(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE, source_type="contacts")]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="o1") is EmploymentStatus.FORMER

    def test_non_org_destination_is_skipped(self) -> None:
        """A person→fund-product link is not employment however its type is named."""
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE, dest_type="hedge-fund-products")]

        index = person_index(relationships, checks=checks)

        assert index.pairs(status=EmploymentStatus.FORMER) == ()

    def test_person_to_person_link_is_skipped(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE, dest_type="people")]

        index = person_index(relationships, checks=checks)

        assert index.pairs(status=EmploymentStatus.FORMER) == ()

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

        index = person_index(relationships, checks=checks)

        assert index.pairs(status=EmploymentStatus.FORMER) == ()

    def test_a_side_without_a_type_is_skipped(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE, dest_type=None)]

        index = person_index(relationships, checks=checks)

        assert index.pairs(status=EmploymentStatus.FORMER) == ()


class TestUnidentifiableOrganization:
    """An org side with no `resourceId` names no company, so it decides nothing.

    (A missing `resourceId` entirely is covered by
    `TestMalformedInput.test_missing_resource_id_is_dropped`.)
    """

    def test_a_blank_organization_id_counts_as_none(self) -> None:
        checks = configure_checks()
        relationships = [person_org("1", type_id=FORMER_TYPE, dest_id="   ")]

        index = person_index(relationships, checks=checks)

        assert index.pairs(status=EmploymentStatus.FORMER) == ()

    def test_one_cannot_clear_a_departure_from_another_company(self) -> None:
        """Keyed on a shared placeholder, this employment would vouch for a person who left
        somewhere else entirely."""
        checks = configure_checks()
        relationships = [
            person_org("1", type_id=FORMER_TYPE, dest_id="oA"),
            person_org("2", type_id=EMPLOYEE_TYPE, dest_id=None),
        ]

        index = person_index(relationships, checks=checks)

        assert index.status(person_id="p1", organization_id="oA") is EmploymentStatus.FORMER
        departed = index.departure(person_id="p1", organization_id="oA")
        assert departed is not None
        assert departed.organization_id == "oA"


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
