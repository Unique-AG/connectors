from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from tests.features.accounts.conftest import make_get_capital_flows_query
from tests.helpers import BASE_URL, resource

_SUBS_URL = f"{BASE_URL}/hedge-fund-account-subscriptions"
_REDS_URL = f"{BASE_URL}/hedge-fund-account-redemptions"


def _page(
    *items: dict[str, object], included: list[dict[str, object]] | None = None
) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": list(items), "included": included or [], "links": {"next": None}},
    )


def _subscription() -> dict[str, object]:
    return {
        "id": "s1",
        "type": "hedge-fund-account-subscriptions",
        "attributes": {
            "amount": 100.0,
            "transactionDate": "2026-02-01T00:00:00.000-0500",
            "status": "COMPLETED",
        },
        "relationships": {"fundAccount": {"data": {"id": "a1", "type": "accounts"}}},
    }


class TestCapitalFlowsAttribution:
    @pytest.mark.asyncio
    @respx.mock
    async def test_a_side_load_with_null_relationships_still_attributes(
        self, client: BackstopClient
    ) -> None:
        """`BackstopApiResource` rejects `relationships: null`; the chip must still resolve."""
        respx.get(_SUBS_URL).mock(
            return_value=_page(
                _subscription(),
                included=[
                    {
                        **resource("a1", "accounts", name="Koch acct"),
                        "relationships": None,
                    },
                ],
            )
        )
        respx.get(_REDS_URL).mock(return_value=_page())

        result = await make_get_capital_flows_query(client).run(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            max_rows=50,
        )

        assert result.unattributed_count == 0
        assert result.flows[0].account is not None
        assert result.flows[0].account.id == "a1"
        assert result.flows[0].account.name == "Koch acct"
