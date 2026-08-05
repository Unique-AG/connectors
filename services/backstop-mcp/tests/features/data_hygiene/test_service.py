"""`DepartedContactDetector`: what the composition root hands it, and what `verify` no longer
needs to be passed.

The scan and classifier it delegates to are covered in `test_departed.py`.
"""

from collections.abc import Sequence
from datetime import date

from backstop_mcp.features.data_hygiene import (
    DepartedContactDetector,
    DepartureSignal,
    create_departed_contact_detector,
)


def _relationship(
    *, type_id: str | None = "456439", end_date: str | None = None
) -> dict[str, object]:
    attributes: dict[str, object] = {
        "sourceEntity": {"resourceId": "p1", "resourceType": "people"},
        "destinationEntity": {"resourceId": "o1", "resourceType": "organizations"},
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
        "id": "er1",
        "attributes": attributes,
        "relationships": relationships,
    }


def _type(type_id: str, name: str) -> dict[str, object]:
    return {
        "type": "entity-relationship-types",
        "id": type_id,
        "attributes": {"name": name},
    }


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
            relationships=[_relationship(type_id="459795")],
            relationship_types=[_type("459795", "is a former employee of")],
        )

        assert departed is not None
        assert departed.signal is DepartureSignal.FORMER_TYPE
        assert departed.relationship_type_name == "is a former employee of"

    def test_configured_ids_decide_when_no_type_side_loaded(self) -> None:
        detector = _detector(former_type_ids=("custom-7",), former_type_markers=())

        departed = detector.verify(
            relationships=[_relationship(type_id="custom-7")], relationship_types=[]
        )

        assert departed is not None
        assert departed.relationship_type_id == "custom-7"

    def test_rules_are_exposed_read_only(self) -> None:
        detector = _detector(former_type_ids=("x",))

        assert detector.rules.former.type_ids == frozenset({"x"})


class TestVerify:
    def test_no_relationships_short_circuits(self) -> None:
        """A person with nothing side-loaded can't be departed — don't classify anything."""
        assert (
            _detector().verify(
                relationships=[],
                relationship_types=[_type("459795", "is a former employee of")],
            )
            is None
        )

    def test_the_clock_defaults_to_today(self) -> None:
        """A real deployment gets `date.today`; only tests pin it."""
        departed = _detector().verify(
            relationships=[_relationship(type_id=None, end_date="2000-01-01")],
            relationship_types=[],
        )

        assert departed is not None
        assert departed.end_date == "2000-01-01"

    def test_an_end_date_after_today_is_not_departed(self) -> None:
        next_year = date.today().replace(year=date.today().year + 1).isoformat()

        assert (
            _detector().verify(
                relationships=[_relationship(type_id=None, end_date=next_year)],
                relationship_types=[],
            )
            is None
        )
