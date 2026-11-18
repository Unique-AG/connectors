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
