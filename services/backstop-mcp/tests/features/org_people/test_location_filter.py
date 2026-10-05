import pytest
from pydantic import ValidationError

from backstop_mcp.features.org_people import LocationFilter


class TestLocationFilter:
    def test_rejects_a_filter_with_no_text_field(self) -> None:
        with pytest.raises(ValidationError, match="needs a city"):
            LocationFilter(primary_only=True)

    def test_blank_text_counts_as_unset(self) -> None:
        with pytest.raises(ValidationError, match="needs a city"):
            LocationFilter(city="   ", country="")

    def test_strips_text(self) -> None:
        assert LocationFilter(city=" London ").city == "London"
