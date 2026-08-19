"""The tool-facing responses: every field of the internal signal has to survive the hop.

A dropped field here is invisible to the feature tests — the scan would still be right and the
caller would still never hear about it — so each response is asserted whole.
"""

from datetime import date
from typing import cast

from backstop_mcp.features.data_hygiene import (
    DepartedContactResponse,
    DepartedEmploymentDto,
    DepartureSignal,
    EmploymentStatus,
)
from backstop_mcp.features.data_hygiene.employment import EmploymentIndex
from backstop_mcp.features.data_hygiene.internal_dto import EmploymentEdgeDto


class TestDepartedResponse:
    def test_a_current_person_has_nothing_to_echo(self) -> None:
        assert DepartedContactResponse.from_departure(None) is None

    def test_every_field_is_carried(self) -> None:
        departed = DepartedEmploymentDto(
            signal=DepartureSignal.FORMER_TYPE,
            organization_id="o1",
            organization_type="organizations",
            end_date=date(2022, 12, 31),
            relationship_type_id="459795",
            relationship_type_name="is a former employee of",
        )

        assert DepartedContactResponse.from_departure(departed) == DepartedContactResponse(
            signal=DepartureSignal.FORMER_TYPE,
            organization_id="o1",
            organization_type="organizations",
            end_date=date(2022, 12, 31),
            relationship_type_id="459795",
            relationship_type_name="is a former employee of",
        )

    def test_the_signal_serializes_as_the_word_the_user_sees(self) -> None:
        response = DepartedContactResponse.from_departure(
            DepartedEmploymentDto(
                signal=DepartureSignal.END_DATE,
                organization_id="o1",
                organization_type="organizations",
            )
        )

        assert response is not None
        assert response.model_dump()["signal"] == "end_date_passed"

    def test_the_schema_publishes_the_possible_signals(self) -> None:
        """Typed as the enum, so a caller reads the two values off the tool schema."""
        schema: dict[str, object] = DepartedContactResponse.model_json_schema()
        definitions = schema["$defs"]
        assert isinstance(definitions, dict)
        signal = cast("dict[str, object]", definitions)["DepartureSignal"]
        assert isinstance(signal, dict)
        values = cast("dict[str, object]", signal)["enum"]
        assert isinstance(values, list)

        assert set(cast("list[object]", values)) == {
            "former_relationship_type",
            "end_date_passed",
        }


class TestEmploymentIndexLinks:
    def test_current_link_carries_both_sides_without_a_signal(self) -> None:
        index = EmploymentIndex(
            [
                EmploymentEdgeDto(
                    person_id="p1",
                    person_type="people",
                    organization_id="o1",
                    organization_type="organizations",
                    relationship_type_id="456439",
                    relationship_type_name="is employee of",
                    status=EmploymentStatus.CURRENT,
                    effective_date=date(2024, 1, 1),
                    departure=None,
                )
            ]
        )

        link = index.links()[0]
        assert link.signal is None
        assert link.end_date is None
        assert link.model_dump() == {
            "status": "current",
            "person_id": "p1",
            "person_type": "people",
            "organization_id": "o1",
            "organization_type": "organizations",
            "relationship_type_id": "456439",
            "relationship_type_name": "is employee of",
        }

    def test_former_link_carries_the_departure_signal(self) -> None:
        index = EmploymentIndex(
            [
                EmploymentEdgeDto(
                    person_id="p1",
                    person_type="people",
                    organization_id="o1",
                    organization_type="organizations",
                    relationship_type_id="459795",
                    relationship_type_name="is a former employee of",
                    status=EmploymentStatus.FORMER,
                    effective_date=date(2022, 12, 31),
                    departure=DepartedEmploymentDto(
                        signal=DepartureSignal.END_DATE,
                        organization_id="o1",
                        organization_type="organizations",
                        end_date=date(2022, 12, 31),
                        relationship_type_id="459795",
                        relationship_type_name="is a former employee of",
                    ),
                )
            ]
        )

        link = index.links()[0]
        assert link.status == "former"
        assert link.signal is DepartureSignal.END_DATE
        assert link.end_date == date(2022, 12, 31)

    def test_links_lists_current_then_former(self) -> None:
        index = EmploymentIndex(
            [
                EmploymentEdgeDto(
                    person_id="p1",
                    person_type="people",
                    organization_id="orgB",
                    organization_type="organizations",
                    relationship_type_id="456439",
                    relationship_type_name="is employee of",
                    status=EmploymentStatus.CURRENT,
                    effective_date=date(2024, 1, 1),
                    departure=None,
                ),
                EmploymentEdgeDto(
                    person_id="p1",
                    person_type="people",
                    organization_id="orgA",
                    organization_type="organizations",
                    relationship_type_id="459795",
                    relationship_type_name="is a former employee of",
                    status=EmploymentStatus.FORMER,
                    effective_date=date(2020, 1, 1),
                    departure=DepartedEmploymentDto(
                        signal=DepartureSignal.FORMER_TYPE,
                        organization_id="orgA",
                        organization_type="organizations",
                        relationship_type_id="459795",
                        relationship_type_name="is a former employee of",
                    ),
                ),
            ]
        )

        links = index.links()
        assert [link.status for link in links] == ["current", "former"]
        assert [link.organization_id for link in links] == ["orgB", "orgA"]
