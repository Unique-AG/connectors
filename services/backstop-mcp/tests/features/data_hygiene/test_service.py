"""`EmploymentIndexFactory`: what the composition root hands it, and what `index_for_person` no
longer needs to be passed.

The scan and classifier it delegates to are covered in `test_employment.py`.
"""

from collections.abc import Sequence
from datetime import date, timedelta

from backstop_mcp.features.data_hygiene import (
    DepartureSignal,
    EmploymentIndexFactory,
    create_employment_index_factory,
)
from tests.features.data_hygiene.helpers import (
    EMPLOYEE_TYPE,
    FORMER_TYPE,
    person_org,
    relationship_types,
)


def _factory(
    *,
    employment_type_ids: Sequence[str] = (),
    employment_type_markers: Sequence[str] = ("employ",),
    former_type_ids: Sequence[str] = (),
    former_type_markers: Sequence[str] = ("former",),
) -> EmploymentIndexFactory:
    return create_employment_index_factory(
        employment_type_ids=employment_type_ids,
        employment_type_markers=employment_type_markers,
        former_type_ids=former_type_ids,
        former_type_markers=former_type_markers,
    )


class TestCreateEmploymentIndexFactory:
    def test_configured_markers_reach_the_verdict(self) -> None:
        index = _factory().index_for_person(
            relationships=[person_org("er1", type_id=FORMER_TYPE)],
            relationship_types=relationship_types(FORMER_TYPE),
        )
        departed = index.departure(person_id="p1", organization_id="o1")

        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE
        assert departed.relationship_type_name == "is a former employee of"

    def test_configured_ids_decide_when_no_type_side_loaded(self) -> None:
        factory = _factory(former_type_ids=("custom-7",), former_type_markers=())

        index = factory.index_for_person(
            relationships=[person_org("er1", type_id="custom-7")], relationship_types=[]
        )
        departed = index.departure(person_id="p1", organization_id="o1")

        assert departed is not None
        assert departed.relationship_type_id == "custom-7"

    def test_rules_are_exposed_read_only(self) -> None:
        factory = _factory(former_type_ids=("x",))

        assert factory.rules.former.type_ids == frozenset({"x"})


class TestIndexForPerson:
    def test_a_person_with_no_relationships_is_not_departed(self) -> None:
        index = _factory().index_for_person(
            relationships=[], relationship_types=relationship_types(FORMER_TYPE)
        )

        assert index.departure(person_id="p1", organization_id="o1") is None

    def test_a_current_employee_is_not_departed(self) -> None:
        index = _factory().index_for_person(
            relationships=[person_org("er1", type_id=EMPLOYEE_TYPE)],
            relationship_types=relationship_types(EMPLOYEE_TYPE),
        )

        assert index.departure(person_id="p1", organization_id="o1") is None

    def test_the_clock_defaults_to_today(self) -> None:
        """A real deployment gets `date.today`; only tests pin it."""
        index = _factory().index_for_person(
            relationships=[person_org("er1", type_id=None, end_date="2000-01-01")],
            relationship_types=[],
        )
        departed = index.departure(person_id="p1", organization_id="o1")

        assert departed is not None
        assert departed.end_date == "2000-01-01"

    def test_an_end_date_after_today_is_not_departed(self) -> None:
        # Days rather than `replace(year=...)`, which raises on a leap day.
        next_year = (date.today() + timedelta(days=366)).isoformat()

        index = _factory().index_for_person(
            relationships=[person_org("er1", type_id=None, end_date=next_year)],
            relationship_types=[],
        )

        assert index.departure(person_id="p1", organization_id="o1") is None

    def test_an_injected_clock_decides_whether_an_end_date_has_passed(self) -> None:
        rules = _factory().rules
        relationships = [person_org("er1", type_id=None, end_date="2026-08-05")]

        before = EmploymentIndexFactory(rules=rules, clock=lambda: date(2026, 8, 4))
        after = EmploymentIndexFactory(rules=rules, clock=lambda: date(2026, 8, 6))

        before_index = before.index_for_person(relationships=relationships, relationship_types=[])
        after_index = after.index_for_person(relationships=relationships, relationship_types=[])

        assert before_index.departure(person_id="p1", organization_id="o1") is None
        assert after_index.departure(person_id="p1", organization_id="o1") is not None
