"""Swagger enums for `GET /{accounts|products}/{id}/{timeSeries}`.

Shared by the query, the published response, and the tool. They cannot live on
`GetTimeSeriesQuery` — that file already imports `TimeSeriesResolvedResponse` — or in
`internal_dto` (Dto classes only). Keep Backstop's `currentMonthNetAssests` spelling.
"""

from typing import Literal, cast, get_args

type TimeSeriesEntityType = Literal["accounts", "products"]
type AccountSeries = Literal[
    "currentMonthIrrs",
    "currentMonthNetAssests",
    "earnings",
    "grossValues",
    "highwaterMarks",
    "incentiveFees",
    "incentiveFeesCharged",
    "irrs",
    "managementFees",
    "newIssueIncomes",
    "percentageOfFundHistory",
    "performanceFeeAccrued",
    "returns",
    "startingValues",
    "totalInvested",
    "totalRedemptions",
    "values",
]
type ProductSeries = Literal[
    "aums",
    "benchmarkAReturns",
    "benchmarkBReturns",
    "benchmarkCReturns",
    "benchmarkDReturns",
    "benchmarkEReturns",
    "benchmarkFReturns",
    "benchmarkGReturns",
    "benchmarkHReturns",
    "expenseDataPoints",
    "incomeDataPoints",
]
type TimeSeriesName = AccountSeries | ProductSeries


def _literal_strings(alias: object) -> frozenset[str]:
    """String members of a PEP 695 `Literal` alias."""
    value: object = getattr(alias, "__value__", alias)
    members = cast("tuple[object, ...]", get_args(value))
    names = tuple(member for member in members if isinstance(member, str))
    assert names and len(names) == len(members), f"{alias} is not a non-empty string Literal"
    return frozenset(names)


ACCOUNT_SERIES: frozenset[str] = _literal_strings(AccountSeries)
PRODUCT_SERIES: frozenset[str] = _literal_strings(ProductSeries)
