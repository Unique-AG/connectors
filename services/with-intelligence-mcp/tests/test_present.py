from pydantic import BaseModel

from with_intelligence_mcp.utils import names, when_either, when_present


class _NamedRecord(BaseModel):
    name: str | None = None


class _Record(BaseModel):
    primary: list[_NamedRecord] | None = None
    secondary: list[_NamedRecord] | None = None


class TestNames:
    def test_none_and_blank_names_contribute_nothing(self) -> None:
        assert names(None) == []
        assert names([_NamedRecord(name="Equity"), _NamedRecord(name=None), _NamedRecord()]) == [
            "Equity"
        ]


class TestPresence:
    def test_an_omitted_field_stays_unknown(self) -> None:
        record = _Record.model_validate({"primary": [{"name": "Equity"}]})
        assert when_present(record, "secondary", names(record.secondary)) is None
        assert when_either(record, "secondary", "missing", names(record.secondary)) is None

    def test_a_present_field_is_returned_even_when_empty(self) -> None:
        record = _Record.model_validate({"primary": [], "secondary": [{"name": "Macro"}]})
        assert when_present(record, "primary", names(record.primary)) == []
        assert when_either(record, "primary", "secondary", names(record.secondary)) == ["Macro"]
