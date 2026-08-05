"""`DepartedContactDetector`: what the composition root hands it, and what `verify` no longer
needs to be passed.

The scan and classifier it delegates to are covered in `test_departed.py`.
"""

from collections.abc import Sequence
from datetime import date, timedelta

from backstop_mcp.features.data_hygiene import (
    DepartedContactDetector,
    DepartureSignal,
    create_departed_contact_detector,
)
from tests.features.data_hygiene.helpers import (
    EMPLOYEE_TYPE,
    FORMER_TYPE,
    person_org,
    relationship_types,
)


def _detector(
    *,
    employment_type_ids: Sequence[str] = (),
    employment_type_markers: Sequence[str] = ("employ",),
    former_type_ids: Sequence[str] = (),
    former_type_markers: Sequence[str] = ("former",),
) -> DepartedContactDetector:
    return create_departed_contact_detector(
        employment_type_ids=employment_type_ids,
        employment_type_markers=employment_type_markers,
        former_type_ids=former_type_ids,
        former_type_markers=former_type_markers,
    )


class TestCreateDepartedContactDetector:
    def test_configured_markers_reach_the_verdict(self) -> None:
        departed = _detector().verify(
            relationships=[person_org("er1", type_id=FORMER_TYPE)],
            relationship_types=relationship_types(FORMER_TYPE),
        )

        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE
        assert departed.relationship_type_name == "is a former employee of"

    def test_configured_ids_decide_when_no_type_side_loaded(self) -> None:
        detector = _detector(former_type_ids=("custom-7",), former_type_markers=())

        departed = detector.verify(
            relationships=[person_org("er1", type_id="custom-7")], relationship_types=[]
        )

        assert departed is not None
        assert departed.relationship_type_id == "custom-7"

    def test_rules_are_exposed_read_only(self) -> None:
        detector = _detector(former_type_ids=("x",))

        assert detector.rules.former.type_ids == frozenset({"x"})


class TestVerify:
    def test_a_person_with_no_relationships_is_not_departed(self) -> None:
        assert (
            _detector().verify(relationships=[], relationship_types=relationship_types(FORMER_TYPE))
            is None
        )

    def test_a_current_employee_is_not_departed(self) -> None:
        assert (
            _detector().verify(
                relationships=[person_org("er1", type_id=EMPLOYEE_TYPE)],
                relationship_types=relationship_types(EMPLOYEE_TYPE),
            )
            is None
        )

    def test_the_clock_defaults_to_today(self) -> None:
        """A real deployment gets `date.today`; only tests pin it."""
        departed = _detector().verify(
            relationships=[person_org("er1", type_id=None, end_date="2000-01-01")],
            relationship_types=[],
        )

        assert departed is not None
        assert departed.end_date == "2000-01-01"

    def test_an_end_date_after_today_is_not_departed(self) -> None:
        # Days rather than `replace(year=...)`, which raises on a leap day.
        next_year = (date.today() + timedelta(days=366)).isoformat()

        assert (
            _detector().verify(
                relationships=[person_org("er1", type_id=None, end_date=next_year)],
                relationship_types=[],
            )
            is None
        )

    def test_an_injected_clock_decides_whether_an_end_date_has_passed(self) -> None:
        rules = _detector().rules
        relationships = [person_org("er1", type_id=None, end_date="2026-08-05")]

        before = DepartedContactDetector(rules=rules, clock=lambda: date(2026, 8, 4))
        after = DepartedContactDetector(rules=rules, clock=lambda: date(2026, 8, 6))

        assert before.verify(relationships=relationships, relationship_types=[]) is None
        assert after.verify(relationships=relationships, relationship_types=[]) is not None
