from backstop_mcp.features.data_hygiene import AsOf, extract_as_of


class TestExtractAsOf:
    def test_returns_none_when_both_missing(self) -> None:
        assert extract_as_of({}) is None
        assert extract_as_of(None) is None
        assert extract_as_of({"name": "Acme"}) is None

    def test_extracts_timestamp_and_by(self) -> None:
        assert extract_as_of(
            {"modifiedTimestamp": "2024-01-01T00:00:00Z", "modifiedBy": "alice"}
        ) == AsOf(modified_timestamp="2024-01-01T00:00:00Z", modified_by="alice")

    def test_accepts_nested_modified_by(self) -> None:
        assert extract_as_of(
            {"modifiedTimestamp": "2024-01-01", "modifiedBy": {"name": "bob"}}
        ) == AsOf(modified_timestamp="2024-01-01", modified_by="bob")

    def test_timestamp_alone_is_enough(self) -> None:
        assert extract_as_of({"modifiedTimestamp": "2024-01-01"}) == AsOf(
            modified_timestamp="2024-01-01", modified_by=None
        )
