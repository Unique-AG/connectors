"""The tool-facing responses: every field of the internal signal has to survive the hop.

A dropped field here is invisible to the feature tests — the scan would still be right and the
user would still never hear about it — so each response is asserted whole.
"""

from datetime import date

from backstop_mcp.coerce import as_object_dict, as_object_list
from backstop_mcp.features.data_hygiene import (
    AsOf,
    DepartedContactResponse,
    DepartedEmployment,
    DepartureSignal,
    as_of_response,
    departed_response,
)


class TestAsOf:
    def test_nothing_to_echo_stays_none(self) -> None:
        assert as_of_response(None) is None

    def test_both_fields_are_carried(self) -> None:
        assert as_of_response(
            AsOf(modified_timestamp="2024-01-01T00:00:00Z", modified_by="alice")
        ) == AsOf(modified_timestamp="2024-01-01T00:00:00Z", modified_by="alice")

    def test_a_partial_signal_is_carried_as_is(self) -> None:
        assert as_of_response(AsOf(modified_timestamp="2024-01-01")) == AsOf(
            modified_timestamp="2024-01-01", modified_by=None
        )


class TestDepartedResponse:
    def test_a_current_person_has_nothing_to_echo(self) -> None:
        assert departed_response(None) is None

    def test_every_field_is_carried(self) -> None:
        departed = DepartedEmployment(
            signal=DepartureSignal.FORMER_TYPE,
            organization_id="o1",
            organization_type="organizations",
            end_date=date(2022, 12, 31),
            relationship_type_id="459795",
            relationship_type_name="is a former employee of",
        )

        assert departed_response(departed) == DepartedContactResponse(
            signal=DepartureSignal.FORMER_TYPE,
            organization_id="o1",
            organization_type="organizations",
            end_date=date(2022, 12, 31),
            relationship_type_id="459795",
            relationship_type_name="is a former employee of",
        )

    def test_the_signal_serializes_as_the_word_the_user_sees(self) -> None:
        response = departed_response(
            DepartedEmployment(
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
        definitions = as_object_dict(schema.get("$defs"))
        assert definitions is not None
        signal = as_object_dict(definitions.get("DepartureSignal"))
        assert signal is not None

        assert set(as_object_list(signal.get("enum"))) == {
            "former_relationship_type",
            "end_date_passed",
        }
