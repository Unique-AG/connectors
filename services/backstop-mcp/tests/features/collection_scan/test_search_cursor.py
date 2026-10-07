import pytest
from fastmcp.exceptions import ToolError

from backstop_mcp.features.collection_scan import SearchCursor, continuation, search_fingerprint


class TestSearchCursor:
    def test_round_trips(self) -> None:
        fingerprint = search_fingerprint("search_people", {"job_title": "CIO"})
        token = SearchCursor(offsets=(150,), fingerprint=fingerprint).encode()

        cursor = SearchCursor.decode(token, fingerprint=fingerprint, collections=1)

        assert cursor.offsets == (150,)

    def test_a_cursor_from_other_arguments_is_rejected(self) -> None:
        token = SearchCursor(
            offsets=(150,), fingerprint=search_fingerprint("search_people", {"job_title": "CIO"})
        ).encode()

        with pytest.raises(ToolError, match="different search"):
            _ = SearchCursor.decode(
                token,
                fingerprint=search_fingerprint("search_people", {"job_title": "CFO"}),
                collections=1,
            )

    @pytest.mark.parametrize("token", ["", "not-a-cursor", "e30"])
    def test_a_malformed_cursor_is_rejected(self, token: str) -> None:
        with pytest.raises(ToolError, match="not one this server issued"):
            _ = SearchCursor.decode(token, fingerprint="x", collections=1)

    def test_the_wrong_number_of_offsets_is_rejected(self) -> None:
        token = SearchCursor(offsets=(1, 2), fingerprint="x").encode()

        with pytest.raises(ToolError, match="not one this server issued"):
            _ = SearchCursor.decode(token, fingerprint="x", collections=1)

    def test_the_fingerprint_ignores_argument_order(self) -> None:
        assert search_fingerprint("t", {"a": 1, "b": [2]}) == search_fingerprint(
            "t", {"b": [2], "a": 1}
        )


class TestContinuation:
    def test_a_full_page_says_how_to_continue(self) -> None:
        result = continuation(
            stop_reason="page_full",
            next_offsets=(100,),
            fingerprint="x",
            rows_returned=100,
        )

        assert result is not None
        assert "Stopped at 100 rows" in result.message
        assert SearchCursor.decode(result.cursor, fingerprint="x", collections=1).offsets == (100,)

    def test_a_finished_search_has_no_continuation(self) -> None:
        assert (
            continuation(
                stop_reason="exhausted",
                next_offsets=(),
                fingerprint="x",
                rows_returned=3,
            )
            is None
        )
