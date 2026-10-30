# contexts

The domain: one folder per feature, and the modules several features share.
[`ARCHITECTURE.md`](../ARCHITECTURE.md) holds the rules this guide works within.

A feature is one domain concept, named in the plural of what it handles: `prices`,
`portfolios`. Features sit side by side. A feature never contains another feature, and organizes
its own modules as its code asks.

Start small and grow only when the code asks for it:

1. A function starts as one module, with its small models inline:
   `contexts/prices/get_price_performance.py` holds `get_price_performance`, `PricePerformance`
   and `PerformanceUnavailableError`.
2. When its inputs or outputs grow past about ten lines, it becomes a folder with the inputs,
   the outputs and the implementation apart. No feature in the demo has grown this far. If
   `record_position` did:

   ```
   contexts/portfolios/record_position/
   ├── __init__.py
   ├── inputs.py             PositionInput
   ├── outputs.py            PositionRejectedError
   └── record_position.py    record_position()
   ```

3. A model several modules of a feature share goes in a file at the feature's top level, such as
   `contexts/portfolios/models.py`, whose `PortfolioValuation` both `record_position` and
   `value_portfolio` return.

A module reads top down: the one public function first, then the private helpers it calls, then
its models. Python 3.14 evaluates annotations lazily, so a function may return a model defined
below it. A function takes at most three positional arguments. A context function that takes
its stores and its input together names them all after a `*`, so a call names what it passes:

```python
async def get_price_performance(
    *,
    upstream: Upstream,
    persistence: Persistence,
    ticker: str,
    start_date: date,
    end_date: date | None,
) -> PricePerformance:
    closes = await get_daily_closes(
        upstream=upstream,
        persistence=persistence,
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
    )
    if len(closes) < _MIN_TRADING_DAYS:
        raise PerformanceUnavailableError(...)
    daily_returns = [later.close / earlier.close - 1 for earlier, later in pairwise(closes)]
    return PricePerformance(
        ...,
        annualized_volatility=_annualized_volatility(daily_returns=daily_returns),
        max_drawdown=_max_drawdown(closes=closes),
    )


def _annualized_volatility(*, daily_returns: list[float]) -> float | None: ...


def _max_drawdown(*, closes: list[DailyClose]) -> float: ...


class PricePerformance(BaseModel): ...


class PerformanceUnavailableError(Exception): ...
```

Extract a private helper when it names a step, not to split a function that reads fine whole.

A context:

- Takes its dependencies as arguments, such as `upstream: Upstream` and
  `persistence: Persistence`. It does not reach for globals or the FastMCP context.
- May read and write the MCP's own storage through `persistence`'s top level:
  `record_position` stores a holding with `save_position`, and `value_portfolio` reads them
  back with `list_positions`. It calls what `persistence` exposes, never SQLAlchemy or Redis
  directly (see [persistence](persistence.md)).
- Returns its own pydantic models, never the upstream's. Map the vendor's model to the
  context's own here, keeping only what the tool needs, so a vendor change stops at this layer.
  The codegen already names generated fields in snake_case, with the vendor's names as aliases.
- Sends upstream calls that do not depend on each other at once, in an `asyncio.TaskGroup`,
  rather than one after another. It does not throttle them itself: the retry policy waits out a
  429, and a limit on requests in flight is the lock `upstream` holds (see
  [upstream](upstream.md#openapi)). A fan-out over a list the user controls, such as every
  position of a portfolio, still bounds how many calls it starts at once, as `value_portfolio`
  does.
- Knows nothing about MCP. It raises its own errors for its own rules
  (`PositionRejectedError`), never a `ToolError`. An `UpstreamError` passes through it as it is:
  `upstream` made it a `ToolError` already.
- May use another feature through that feature's top level: `value_portfolio` prices each
  position with `get_latest_close`, imported from `<package>.contexts.prices`. If two features
  need each other, the shared part is a third feature.

A helper several features use, with no domain of its own, is a module beside the features, such
as `contexts/pages.py` for paging through a list. It imports no feature, so a feature can use it
without a cycle. Once it holds a domain concept, it becomes a feature. When another layer needs
it too, it belongs in `shared/`.
