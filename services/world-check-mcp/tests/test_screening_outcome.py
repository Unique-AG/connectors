from world_check_mcp.contexts.screening import watchlist_results
from world_check_mcp.upstream import ResultWire


def test_watchlist_results_keeps_only_watchlist_provider() -> None:
    watchlist = ResultWire(resultId="a", providerType="WATCHLIST")
    results = [
        watchlist,
        ResultWire(resultId="b", providerType="PASSPORT_CHECK"),
        ResultWire(resultId="c", providerType="MEDIA_CHECK"),
        ResultWire(resultId="d"),
    ]

    assert watchlist_results(results) == [watchlist]


def test_a_result_without_names_is_titled_by_its_first_matched_term() -> None:
    result = ResultWire.model_validate(
        {
            "resultId": "a",
            "names": None,
            "matchedTerms": [{"term": ""}, {"term": "Ada Lovell", "type": "AKA"}],
        }
    )

    assert result.matched_name == "Ada Lovell"


def test_a_result_without_names_or_terms_has_no_name() -> None:
    assert ResultWire.model_validate({"resultId": "a", "matchedTerms": None}).matched_name is None
