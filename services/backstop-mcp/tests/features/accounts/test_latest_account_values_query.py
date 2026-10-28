import logging

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from tests.features.accounts.conftest import make_get_latest_account_values_query
from tests.helpers import BASE_URL

_LOGGER = "backstop_mcp.features.accounts.queries.get_latest_account_values_query"


def _values(account_id: str, response: httpx.Response) -> None:
    respx.get(f"{BASE_URL}/accounts/{account_id}/values").mock(return_value=response)


def _point(value: float) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                {
                    "id": "p1",
                    "type": "time-series",
                    "attributes": {"date": "2026-07-31", "value": value, "valueStatus": "ACTUAL"},
                }
            ]
        },
    )


class TestFailedAccounts:
    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_accounts_log_one_warning_per_call_with_sample_ids(
        self, client: BackstopClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        failing = [str(100 + index) for index in range(7)]
        for account_id in failing:
            _values(account_id, httpx.Response(500, json={"errors": []}))
        _values("1", _point(10.0))

        with caplog.at_level(logging.DEBUG, logger=_LOGGER):
            latest = await make_get_latest_account_values_query(client).run(
                account_ids=["1", *failing]
            )

        assert [value.account_id for value in latest if value.error is not None] == failing
        records = [record for record in caplog.records if record.name == _LOGGER]
        [warning] = [record for record in records if record.levelno == logging.WARNING]
        assert warning.message == "Latest account values failed"
        assert warning.__dict__["count"] == 7
        assert warning.__dict__["sample_ids"] == failing[:5]
        details = [record for record in records if record.message == "Latest account value failed"]
        assert len(details) == 7
        assert {record.levelno for record in details} == {logging.DEBUG}

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_failed_account_logs_no_warning(
        self, client: BackstopClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        _values("1", _point(10.0))

        with caplog.at_level(logging.DEBUG, logger=_LOGGER):
            await make_get_latest_account_values_query(client).run(account_ids=["1"])

        assert [record for record in caplog.records if record.name == _LOGGER] == []
