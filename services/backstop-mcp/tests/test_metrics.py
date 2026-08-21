"""The one `View` behind the two catalog histograms.

`catalog_get_duration_seconds` (demand) and `catalog_fetch_duration_seconds` (walks) are read
together: subtracting their `_count`s gives the requests caching and coalescing already remove,
and comparing their buckets gives the latency a TTL would buy. Both only mean something if the
two agree bucket-for-bucket, which is why one View defines them rather than each instrument
carrying its own boundary list. That is what this asserts — the numbers themselves are a
judgement call, their being *identical* is a contract.

A local `MeterProvider` is used rather than `configure_metrics`, which installs a process-global
provider that cannot be set twice or torn down.
"""

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import Histogram, InMemoryMetricReader

from backstop_mcp.metrics import CATALOG_DURATION_VIEW

_CATALOG_HISTOGRAMS = ("catalog_get_duration_seconds", "catalog_fetch_duration_seconds")


def _recorded_bounds(*names: str) -> dict[str, tuple[float, ...]]:
    """Record one value on each named histogram and read back the buckets it landed in."""
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], views=[CATALOG_DURATION_VIEW])
    meter = provider.get_meter("test")
    for name in names:
        meter.create_histogram(name, unit="s").record(0.4, {"catalog": "activity-tag"})

    data = reader.get_metrics_data()
    assert data is not None
    bounds: dict[str, tuple[float, ...]] = {}
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                # A View that silently changed the aggregation would otherwise read as a bucket
                # mismatch rather than as what it is.
                assert isinstance(metric.data, Histogram), metric.name
                bounds[metric.name] = tuple(metric.data.data_points[0].explicit_bounds)
    return bounds


class TestCatalogDurationView:
    def test_both_catalog_histograms_get_the_same_buckets_from_the_one_view(self) -> None:
        bounds = _recorded_bounds(*_CATALOG_HISTOGRAMS)

        assert set(bounds) == set(_CATALOG_HISTOGRAMS)
        assert len(set(bounds.values())) == 1

    def test_the_buckets_resolve_a_cache_hit_and_a_slow_walk_alike(self) -> None:
        """One list has to cover both halves of the pair, which span very different scales.

        A cache-served `get` is microseconds; the custom-field schema walk is many pages. With
        boundaries for only one of those, the other collapses into a single bucket and the
        comparison the view exists for says nothing.
        """
        bounds = _recorded_bounds("catalog_get_duration_seconds")["catalog_get_duration_seconds"]

        assert min(bounds) <= 0.001
        assert max(bounds) >= 30.0
        assert sorted(bounds) == list(bounds)

    def test_the_view_does_not_capture_the_unrelated_backstop_histograms(self) -> None:
        """The name pattern is a wildcard, so it is worth pinning what it does not match."""
        bounds = _recorded_bounds(
            "catalog_get_duration_seconds",
            "backstop_request_duration_seconds",
            "backstop_concurrency_wait_seconds",
        )

        catalog_bounds = bounds["catalog_get_duration_seconds"]
        assert bounds["backstop_request_duration_seconds"] != catalog_bounds
        assert bounds["backstop_concurrency_wait_seconds"] != catalog_bounds
