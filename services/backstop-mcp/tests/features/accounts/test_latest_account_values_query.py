"""`GetLatestAccountValuesQuery`: one account failing costs that figure, and is logged once."""

import logging

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from tests.features.accounts.conftest import make_get_latest_account_values_query
from tests.helpers import BASE_URL, aggregated_warning


class TestFailedSeries:
    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_accounts_produce_one_warning_per_call(
        self, client: BackstopClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        account_ids = [str(6000 + index) for index in range(7)]
        for account_id in account_ids:
            respx.get(f"{BASE_URL}/accounts/{account_id}/values").mock(
                return_value=httpx.Response(500, json={"errors": []})
            )

        with caplog.at_level(logging.WARNING):
            latest = await make_get_latest_account_values_query(client).run(account_ids=account_ids)

        assert [value.account_id for value in latest if value.error is not None] == account_ids
        record = aggregated_warning(
            caplog,
            "accounts.latest_values.series_failed",
            count=7,
            sample_ids=account_ids[:5],
        )
        assert record.__dict__["error_type"] == "BackstopApiError"

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_bug_among_failed_accounts_is_logged_as_an_error_with_its_stack(
        self, client: BackstopClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        respx.get(f"{BASE_URL}/accounts/6100/values").mock(
            return_value=httpx.Response(500, json={"errors": []})
        )
        respx.get(f"{BASE_URL}/accounts/6101/values").mock(side_effect=RuntimeError("boom"))

        with caplog.at_level(logging.WARNING):
            latest = await make_get_latest_account_values_query(client).run(
                account_ids=["6100", "6101"]
            )

        assert [value.account_id for value in latest if value.error is not None] == [
            "6100",
            "6101",
        ]
        records = [
            record
            for record in caplog.records
            if record.getMessage() == "accounts.latest_values.series_failed"
        ]
        assert len(records) == 1
        assert records[0].levelno == logging.ERROR
        assert records[0].exc_info is not None
        assert records[0].__dict__["error_type"] == "RuntimeError"
        assert records[0].__dict__["count"] == 2
