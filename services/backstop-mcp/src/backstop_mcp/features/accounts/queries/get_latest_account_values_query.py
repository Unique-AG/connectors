"""Latest `values` point for each of a set of accounts.

`get_product_investors` is the consumer, and only when the caller opted in. There is no bulk
path: table-data answers a product id with an empty table, and `GET /time-series` is 400. So
this is one `GET /accounts/{id}/values?sort=-date` page per account, gathered. The per-user
request gate on `BackstopClient` bounds how many are in flight, so gathering does not breach
Backstop's concurrency limit. The caller owns the account cap.

One account failing costs that account's figure, not the answer. Auth and rate-limit errors
still abort: the rest of the batch would fail the same way. A non-`Exception` (cancellation)
is re-raised, never folded into a row.
"""

import asyncio
import logging
from collections.abc import Sequence
from urllib.parse import quote

from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopAuthError,
    BackstopClient,
    BackstopRateLimitError,
    BackstopTransientAuthError,
)
from backstop_mcp.features.accounts.internal_dto import AccountLatestValueDto, SeriesFigureDto
from backstop_mcp.features.accounts.utils import fetch_series

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

# The rest of the batch would fail the same way, so these abort instead of costing one row.
_ABORTS_BATCH = (BackstopAuthError, BackstopTransientAuthError, BackstopRateLimitError)


class GetLatestAccountValuesQuery:
    """Each account's newest `values` point, and the newest one carrying a number."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(self, *, account_ids: Sequence[str]) -> tuple[AccountLatestValueDto, ...]:
        with _tracer.start_as_current_span("accounts.query.latest_values") as span:
            span.set_attribute("requested", len(account_ids))
            settled = await asyncio.gather(
                *(
                    fetch_series(self._client, f"/accounts/{quote(account_id, safe='')}/values")
                    for account_id in account_ids
                ),
                return_exceptions=True,
            )
            latest = tuple(
                self._outcome(account_id, result)
                for account_id, result in zip(account_ids, settled, strict=True)
            )
            logger.info(
                "accounts.latest_values.fetched",
                extra={
                    "requested": len(account_ids),
                    "valued": sum(
                        1
                        for value in latest
                        if value.figure is not None and value.figure.valued is not None
                    ),
                    "failed": sum(1 for value in latest if value.error is not None),
                },
            )
            return latest

    def _outcome(
        self, account_id: str, settled: SeriesFigureDto | BaseException | None
    ) -> AccountLatestValueDto:
        if isinstance(settled, BaseException):
            if not isinstance(settled, Exception) or isinstance(settled, _ABORTS_BATCH):
                raise settled
            logger.warning(
                "accounts.latest_values.series_failed",
                extra={"account_id": account_id},
                exc_info=settled,
            )
            return AccountLatestValueDto(
                account_id=account_id, error=f"{type(settled).__name__}: {settled}"
            )
        return AccountLatestValueDto(account_id=account_id, figure=settled)
