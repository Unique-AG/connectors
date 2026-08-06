"""The tool-facing echoes: every field of the internal signal has to survive the hop.

A dropped field here is invisible to the feature tests — the scan would still be right and the
user would still never hear about it — so each echo is asserted whole.
"""

from backstop_mcp.coerce import as_object_dict, as_object_list
from backstop_mcp.features.data_hygiene import (
    AsOf,
    AsOfEcho,
    DepartedContactEcho,
    DepartedEmployment,
    DepartureSignal,
    as_of_echo,
    departed_echo,
)


class TestAsOfEcho:
    def test_nothing_to_echo_stays_none(self) -> None:
        assert as_of_echo(None) is None

    def test_both_fields_are_carried(self) -> None:
        assert as_of_echo(
            AsOf(modified_timestamp="2024-01-01T00:00:00Z", modified_by="alice")
        ) == AsOfEcho(modified_timestamp="2024-01-01T00:00:00Z", modified_by="alice")

    def test_a_partial_signal_is_carried_as_is(self) -> None:
        assert as_of_echo(AsOf(modified_timestamp="2024-01-01")) == AsOfEcho(
            modified_timestamp="2024-01-01", modified_by=None
        )


class TestDepartedEcho:
    def test_a_current_person_has_nothing_to_echo(self) -> None:
        assert departed_echo(None) is None

    def test_every_field_is_carried(self) -> None:
        departed = DepartedEmployment(
            signal=DepartureSignal.FORMER_TYPE,
            organization_id="o1",
            organization_type="organizations",
            end_date="2022-12-31",
            relationship_type_id="459795",
            relationship_type_name="is a former employee of",
        )

        assert departed_echo(departed) == DepartedContactEcho(
            signal=DepartureSignal.FORMER_TYPE,
            organization_id="o1",
            organization_type="organizations",
            end_date="2022-12-31",
            relationship_type_id="459795",
            relationship_type_name="is a former employee of",
        )

    def test_the_signal_serializes_as_the_word_the_user_sees(self) -> None:
        echo = departed_echo(
            DepartedEmployment(
                signal=DepartureSignal.END_DATE,
                organization_id="o1",
                organization_type="organizations",
            )
        )

        assert echo is not None
        assert echo.model_dump()["signal"] == "end_date_passed"

    def test_the_schema_publishes_the_possible_signals(self) -> None:
        """Typed as the enum, so a caller reads the two values off the tool schema."""
        schema: dict[str, object] = DepartedContactEcho.model_json_schema()
        definitions = as_object_dict(schema.get("$defs"))
        assert definitions is not None
        signal = as_object_dict(definitions.get("DepartureSignal"))
        assert signal is not None

        assert set(as_object_list(signal.get("enum"))) == {
            "former_relationship_type",
            "end_date_passed",
        }
