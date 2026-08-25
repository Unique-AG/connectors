from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.features.accounts.tools.get_capital_flows import (
    CapitalFlowRowResponse,
    CapitalFlowsResolvedResponse,
    get_capital_flows,
)
from backstop_mcp.server.tools import TOOLS
from tests.helpers import BASE_URL, recorded_requests, resource, tool_client
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload


def tenant(name: str) -> str:
    return f"{BASE_URL}/{name}"


def _page(
    *items: dict[str, object], included: list[dict[str, object]] | None = None
) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": list(items), "included": included or [], "links": {"next": None}},
    )


def _sub(
    sub_id: str,
    *,
    account_id: str | None = "a1",
    amount: float = 100.0,
    status: str = "COMPLETED",
    share_class: str | None = "A",
    **attrs: object,
) -> dict[str, object]:
    relationships: dict[str, object] = {}
    if account_id is not None:
        relationships["fundAccount"] = {"data": {"id": account_id, "type": "accounts"}}
    payload: dict[str, object] = {
        "amount": amount,
        "transactionDate": "2026-02-01T00:00:00.000-0500",
        "status": status,
        "legacyTransactionType": "SUBSCRIPTION",
    }
    if share_class is not None:
        payload["shareClass"] = share_class
        payload["shareSeries"] = "1"
    payload.update(attrs)
    return {
        "id": sub_id,
        "type": "hedge-fund-account-subscriptions",
        "attributes": payload,
        "relationships": relationships,
    }


def _red(
    red_id: str,
    *,
    original_id: str | None = None,
    amount: float = 50.0,
    status: str = "COMPLETED",
) -> dict[str, object]:
    relationships: dict[str, object] = {}
    if original_id is not None:
        relationships["originalSubscription"] = {
            "data": {"id": original_id, "type": "hedge-fund-account-subscriptions"}
        }
    return {
        "id": red_id,
        "type": "hedge-fund-account-redemptions",
        "attributes": {
            "amount": amount,
            "transactionDate": "2026-03-01T00:00:00.000-0500",
            "status": status,
            "legacyTransactionType": "REDEMPTION",
            "liquidating": True,
        },
        "relationships": relationships,
    }


class TestGetCapitalFlows:
    def test_is_registered_and_requires_a_date_window(self) -> None:
        assert get_capital_flows in TOOLS
        doc = get_capital_flows.__doc__ or ""
        assert "share_class" in doc or "share class" in doc
        assert "unattributed" in doc or "originalSubscription" in doc
        assert "account_ids" in doc
        assert "transaction_date" in doc

    @pytest.mark.asyncio
    @respx.mock
    async def test_two_calls_pin_date_filters_and_includes(self) -> None:
        base_url = tenant("cf-pin")
        subs = respx.get(f"{base_url}/hedge-fund-account-subscriptions").mock(
            return_value=_page(
                _sub("s1"),
                included=[
                    {
                        **resource("a1", "accounts", name="Koch acct"),
                        "relationships": {"owner": {"data": {"id": "o1", "type": "contacts"}}},
                    },
                    resource("o1", "contacts", name="Koch"),
                ],
            )
        )
        reds = respx.get(f"{base_url}/hedge-fund-account-redemptions").mock(
            return_value=_page(
                _red("r1", original_id="s1"),
                included=[
                    {
                        **_sub("s1"),
                        "relationships": {
                            "fundAccount": {"data": {"id": "a1", "type": "accounts"}}
                        },
                    },
                    {
                        **resource("a1", "accounts", name="Koch acct"),
                        "relationships": {"owner": {"data": {"id": "o1", "type": "contacts"}}},
                    },
                    resource("o1", "contacts", name="Koch"),
                ],
            )
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_capital_flows(
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 12, 31),
                    client=client,
                ),
                CapitalFlowsResolvedResponse,
            )

        assert subs.call_count == 1
        assert reds.call_count == 1
        sub_params = recorded_requests(subs.calls)[0].url.params
        red_params = recorded_requests(reds.calls)[0].url.params
        assert sub_params["filter[transactionDate][ge]"] == "2026-01-01"
        assert sub_params["filter[transactionDate][le]"] == "2026-12-31"
        assert sub_params["include"] == "fundAccount.owner"
        assert red_params["include"] == "originalSubscription.fundAccount.owner"
        assert result.request_count == 2
        assert result.non_actual_count == 0
        assert result.scan_truncated is False
        payload = tool_payload(result)
        flows = [object_dict(item) for item in object_list(payload["flows"])]
        kinds = {item["kind"]: item for item in flows}
        assert kinds["subscription"]["share_class"] == "A"
        assert object_dict(kinds["subscription"]["account"])["id"] == "a1"
        assert kinds["redemption"]["unattributed"] is False
        assert object_dict(kinds["redemption"]["account"])["id"] == "a1"
        assert object_dict(kinds["redemption"]["owner"])["id"] == "o1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_owner_id_keeps_redemptions_attributed_through_the_account(self) -> None:
        """Redemptions have no owner of their own; it lives on originalSubscription.fundAccount.

        The walk must include `.owner` or owner_id filtering drops every redemption that
        otherwise resolved to an account.
        """
        base_url = tenant("cf-red-owner")
        respx.get(f"{base_url}/hedge-fund-account-subscriptions").mock(return_value=_page())
        respx.get(f"{base_url}/hedge-fund-account-redemptions").mock(
            return_value=_page(
                _red("r1", original_id="s1"),
                included=[
                    {
                        **_sub("s1"),
                        "relationships": {
                            "fundAccount": {"data": {"id": "a1", "type": "accounts"}}
                        },
                    },
                    {
                        **resource("a1", "accounts", name="Koch acct"),
                        "relationships": {"owner": {"data": {"id": "o1", "type": "contacts"}}},
                    },
                    resource("o1", "contacts", name="Koch"),
                ],
            )
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_capital_flows(
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 12, 31),
                    owner_id="o1",
                    client=client,
                ),
                CapitalFlowsResolvedResponse,
            )

        flows = [object_dict(item) for item in object_list(tool_payload(result)["flows"])]
        assert [item["id"] for item in flows] == ["r1"]
        assert object_dict(flows[0]["owner"])["id"] == "o1"
        assert result.redemption_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_orphan_redemption_is_unattributed_not_dropped(self) -> None:
        base_url = tenant("cf-orphan")
        respx.get(f"{base_url}/hedge-fund-account-subscriptions").mock(return_value=_page())
        respx.get(f"{base_url}/hedge-fund-account-redemptions").mock(
            return_value=_page(_red("r-orphan"))
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_capital_flows(
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 12, 31),
                    client=client,
                ),
                CapitalFlowsResolvedResponse,
            )

        flows = [object_dict(item) for item in object_list(tool_payload(result)["flows"])]
        assert len(flows) == 1
        assert flows[0]["unattributed"] is True
        assert result.unattributed_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_estimates_are_omitted(self) -> None:
        base_url = tenant("cf-est")
        respx.get(f"{base_url}/hedge-fund-account-subscriptions").mock(
            return_value=_page(_sub("s-est", status="ESTIMATED"), _sub("s-ok"))
        )
        respx.get(f"{base_url}/hedge-fund-account-redemptions").mock(return_value=_page())

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_capital_flows(
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 12, 31),
                    client=client,
                ),
                CapitalFlowsResolvedResponse,
            )

        flows = [object_dict(item) for item in object_list(tool_payload(result)["flows"])]
        assert [item["id"] for item in flows] == ["s-ok"]
        assert result.non_actual_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_account_ids_filter_applies_before_the_row_cap(self) -> None:
        base_url = tenant("cf-acct")
        respx.get(f"{base_url}/hedge-fund-account-subscriptions").mock(
            return_value=_page(
                _sub("s-other", account_id="a-other", amount=9.0),
                _sub("s-keep", account_id="a-keep", amount=100.0),
                included=[
                    {
                        **resource("a-other", "accounts", name="Other"),
                        "relationships": {"owner": {"data": {"id": "o-other", "type": "contacts"}}},
                    },
                    {
                        **resource("a-keep", "accounts", name="Keep"),
                        "relationships": {"owner": {"data": {"id": "o-keep", "type": "contacts"}}},
                    },
                    resource("o-other", "contacts", name="Other Co"),
                    resource("o-keep", "contacts", name="Keep Co"),
                ],
            )
        )
        respx.get(f"{base_url}/hedge-fund-account-redemptions").mock(return_value=_page())

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_capital_flows(
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 12, 31),
                    account_ids=["a-keep"],
                    max_rows=1,
                    client=client,
                ),
                CapitalFlowsResolvedResponse,
            )

        payload = tool_payload(result)
        flows = [object_dict(item) for item in object_list(payload["flows"])]
        assert [item["id"] for item in flows] == ["s-keep"]
        assert result.total == 1
        assert result.truncated is False
        assert result.request_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_truncated_is_true_when_matches_exceed_max_rows(self) -> None:
        base_url = tenant("cf-trunc")
        respx.get(f"{base_url}/hedge-fund-account-subscriptions").mock(
            return_value=_page(
                _sub("s1", account_id="a1"),
                _sub("s2", account_id="a1"),
                included=[
                    {
                        **resource("a1", "accounts", name="Koch acct"),
                        "relationships": {"owner": {"data": {"id": "o1", "type": "contacts"}}},
                    },
                    resource("o1", "contacts", name="Koch"),
                ],
            )
        )
        respx.get(f"{base_url}/hedge-fund-account-redemptions").mock(return_value=_page())

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_capital_flows(
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 12, 31),
                    owner_id="o1",
                    max_rows=1,
                    client=client,
                ),
                CapitalFlowsResolvedResponse,
            )

        assert result.total == 2
        assert result.truncated is True
        assert len(object_list(tool_payload(result)["flows"])) == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_undated_flows_sort_last_and_do_not_crowd_the_row_cap(self) -> None:
        """`flows` is documented newest-first, and `max_rows` slices after the sort.

        Sorting `(date is None, date)` descending puts the undated group first, so an undated
        row would take the only slot a dated one should have had.
        """
        base_url = tenant("cf-undated")
        respx.get(f"{base_url}/hedge-fund-account-subscriptions").mock(
            return_value=_page(
                _sub("s-undated", account_id=None, transactionDate=None),
                _sub("s-dated", account_id=None),
            )
        )
        respx.get(f"{base_url}/hedge-fund-account-redemptions").mock(return_value=_page())

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_capital_flows(
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 12, 31),
                    max_rows=1,
                    client=client,
                ),
                CapitalFlowsResolvedResponse,
            )

        flows = [object_dict(item) for item in object_list(tool_payload(result)["flows"])]
        assert [item["id"] for item in flows] == ["s-dated"]
        assert result.total == 2
        assert result.truncated is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_subscription_with_no_account_include_is_flagged_unattributed(self) -> None:
        """`unattributed` covers both kinds: a subscription can lose its `fundAccount` too."""
        base_url = tenant("cf-sub-orphan")
        respx.get(f"{base_url}/hedge-fund-account-subscriptions").mock(
            return_value=_page(_sub("s-orphan", account_id=None))
        )
        respx.get(f"{base_url}/hedge-fund-account-redemptions").mock(return_value=_page())

        async with tool_client(base_url) as client:
            result = tool_model(
                await get_capital_flows(
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 12, 31),
                    client=client,
                ),
                CapitalFlowsResolvedResponse,
            )

        flows = [object_dict(item) for item in object_list(tool_payload(result)["flows"])]
        assert flows[0]["unattributed"] is True
        assert result.unattributed_count == 1
        published = CapitalFlowRowResponse.model_fields["unattributed"].description or ""
        assert "subscription" in published
        assert "redemption" in published
