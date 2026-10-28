from backstop_mcp.utils import sample_ids


class TestSampleIds:
    def test_keeps_the_first_five(self) -> None:
        assert sample_ids(str(index) for index in range(8)) == ["0", "1", "2", "3", "4"]

    def test_skips_missing_ids_before_counting(self) -> None:
        assert sample_ids([None, "a", None, "b"]) == ["a", "b"]

    def test_returns_an_empty_list_for_no_ids(self) -> None:
        assert sample_ids([]) == []
