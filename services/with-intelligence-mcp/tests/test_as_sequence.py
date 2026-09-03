"""The two coercions that absorb the vendor's inconsistent array encoding.

Each has been wrong in production once, so both directions are pinned here rather than left to
the feature tests that happen to exercise them.
"""

from with_intelligence_mcp.with_intelligence_client import as_sequence, as_single


class TestAsSequence:
    def test_a_list_passes_through(self) -> None:
        assert as_sequence([{"id": 1}, {"id": 2}]) == [{"id": 1}, {"id": 2}]

    def test_an_index_keyed_object_flattens_in_key_order(self) -> None:
        """How `consultants` actually arrives, despite being declared an array."""
        assert as_sequence({"1": {"id": 2}, "0": {"id": 1}}) == [{"id": 1}, {"id": 2}]

    def test_key_order_is_numeric_not_lexicographic(self) -> None:
        flattened = as_sequence({str(index): {"id": index} for index in range(11)})
        assert flattened == [{"id": index} for index in range(11)]

    def test_a_single_record_is_wrapped_not_shredded(self) -> None:
        """Reading `.values()` off a single record turned it into `[4, 'Real Assets']`."""
        assert as_sequence({"id": 4, "name": "Real Assets"}) == [{"id": 4, "name": "Real Assets"}]

    def test_a_record_whose_keys_are_mixed_is_a_single_record(self) -> None:
        assert as_sequence({"0": "a", "name": "b"}) == [{"0": "a", "name": "b"}]

    def test_an_empty_object_is_an_empty_list(self) -> None:
        assert as_sequence({}) == []

    def test_a_non_container_passes_through_for_pydantic_to_reject(self) -> None:
        assert as_sequence("nonsense") == "nonsense"
        assert as_sequence(None) is None


class TestAsSingle:
    def test_an_object_passes_through(self) -> None:
        assert as_single({"id": 4}) == {"id": 4}

    def test_a_one_element_list_collapses(self) -> None:
        assert as_single([{"id": 4}]) == {"id": 4}

    def test_a_longer_list_keeps_the_first(self) -> None:
        """Lossy, but only in the case the spec says cannot happen — the alternative is a
        failed tool call."""
        assert as_single([{"id": 4}, {"id": 5}]) == {"id": 4}

    def test_an_empty_list_becomes_none(self) -> None:
        assert as_single([]) is None

    def test_a_non_container_passes_through(self) -> None:
        assert as_single("nonsense") == "nonsense"
        assert as_single(None) is None
