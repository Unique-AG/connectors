"""Newest `values` point per account: one GET each, gathered under the client's concurrency gate.

One account failing costs that figure. Auth and rate-limit errors abort the batch.
"""

import asyncio
import logging
from collections.abc import Sequence
from urllib.parse import quote

from mcp_observability import traced

from backstop_mcp.backstop_client import BATCH_ABORTING_ERRORS, BackstopClient
from backstop_mcp.features.accounts.internal_dto import AccountLatestValueDto, SeriesFigureDto
from backstop_mcp.features.accounts.utils import fetch_series
from backstop_mcp.utils import sample_ids

logger = logging.getLogger(__name__)


def _value_counts(latest: Sequence[AccountLatestValueDto]) -> dict[str, int]:
    return {
        "valued": sum(
            1 for value in latest if value.figure is not None and value.figure.valued is not None
        ),
        "failed": sum(1 for value in latest if value.error is not None),
    }


class GetLatestAccountValuesQuery:
    """Each account's newest `values` point, and the newest one carrying a number."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    @traced(
        arguments=lambda args: {"requested": len(args["account_ids"])},
        result=_value_counts,
    )
    async def run(self, *, account_ids: Sequence[str]) -> tuple[AccountLatestValueDto, ...]:
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
        failed_ids = [value.account_id for value in latest if value.error is not None]
        if failed_ids:
            logger.warning(
                "Latest account values failed",
                extra={"count": len(failed_ids), "sample_ids": sample_ids(failed_ids)},
            )
        return latest

    def _outcome(
        self, account_id: str, settled: SeriesFigureDto | BaseException | None
    ) -> AccountLatestValueDto:
        if isinstance(settled, BaseException):
            if not isinstance(settled, Exception) or isinstance(settled, BATCH_ABORTING_ERRORS):
                raise settled
            logger.debug(
                "Latest account value failed",
                extra={"account_id": account_id},
                exc_info=settled,
            )
            return AccountLatestValueDto(
                account_id=account_id, error=f"{type(settled).__name__}: {settled}"
            )
        return AccountLatestValueDto(account_id=account_id, figure=settled)
