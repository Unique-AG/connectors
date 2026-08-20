"""Fidelity: `fetch_holdings_table` against the real recorded payloads, not hand-written fixtures.

Every other test in this feature builds its own JSON, which means a field Backstop renames — or an
alias that was wrong from the start — stays invisible: the fixture and the model are written from
the same mistaken assumption. These tests replay the responses actually recorded from the live
instance (`docs/json/`) through the real fetch function, so the projection is checked against what
Backstop sends rather than against what we assumed it sends.

Driven through `respx` at the feature boundary — no private helpers — so a refactor inside the
module cannot quietly stop this from testing anything.
"""

import json
from pathlib import Path
from typing import cast

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.accounts import (
    HoldingListingDto,
    HoldingRowDto,
    fetch_holdings_table,
)
from tests.helpers import BASE_URL

# tests/features/accounts/ -> tests -> backstop-mcp -> services -> repo root
_RECORDINGS = Path(__file__).resolve().parents[5] / "docs" / "json"
_URL = f"{BASE_URL}/bsg-account-table-data"

_POPULATED = (
    "023-bsg-account-table-data-200.json",
    "046-fb-rm-lg-26-bsg-account-table-data-200.json",
)
# The two fail-open bodies: a product id, and a nonexistent id. Both are empty 200s.
_EMPTY = ("037-bsg-account-table-data-200.json", "038-bsg-account-table-data-200.json")


def _recorded_body(name: str) -> dict[str, object]:
    """The `body` of one recorded probe, as `explore.py` wrote it."""
    if not _RECORDINGS.is_dir():
        pytest.skip(f"recordings directory {_RECORDINGS} not present in this checkout")
    path = _RECORDINGS / name
    # A missing file inside a present directory is a failure, not a skip: a silent skip is how a
    # fidelity test stops testing anything without anyone noticing.
    assert path.is_file(), f"expected recording {path}"
    record = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    body = record["body"]
    assert isinstance(body, dict), f"{name} has no JSON object body"
    return cast("dict[str, object]", body)


async def _replay(client: BackstopClient, name: str, **kwargs: bool) -> HoldingListingDto:
    respx.get(_URL).mock(return_value=httpx.Response(200, json=_recorded_body(name)))
    return await fetch_holdings_table(client, entity_id="recording", **kwargs)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("name", _POPULATED)
async def test_a_recorded_table_projects_every_row(client: BackstopClient, name: str) -> None:
    """No row is dropped, and Backstop's own counts agree with the rows it sent."""
    result = await _replay(client, name, include_closed=True)

    assert result.rows, "recording has no rows to check"
    assert result.rows_dropped == 0
    assert len(result.rows) == result.all_count


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("name", _POPULATED)
async def test_every_projected_field_is_populated_somewhere(
    client: BackstopClient, name: str
) -> None:
    """A field nothing ever populates is the signature of a wrong alias.

    The exclusions are fields genuinely empty for every account on this tenant (`"-"` commitments,
    a zero share of master) or only ever set on the fallback path — their absence here says
    nothing about the alias. Everything else must be non-`None` on at least one recorded row.
    """
    result = await _replay(client, name, include_closed=True)

    empty_on_this_tenant = {
        "commitment",
        "unfunded_commitment",
        "percentage_of_master",
        "balance_as_of",
        "balance_status",
        "figure_errors",
        "closed",
    }
    checked = set(HoldingRowDto.model_fields) - empty_on_this_tenant
    unpopulated = {
        field for field in checked if all(getattr(row, field) is None for row in result.rows)
    }

    assert unpopulated == set()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("name", _POPULATED)
async def test_the_recorded_balance_matches_the_documented_series(
    client: BackstopClient, name: str
) -> None:
    """The claim the whole primary path rests on.

    Account 29431089's newest `/accounts/29431089/values` point is 3619868606.0, recorded in
    `docs/json/024`. A wrong `balance` alias would make this `None` while every hand-written test
    still passed.
    """
    result = await _replay(client, name, include_closed=True)
    rows = {row.account_id: row for row in result.rows}

    row = rows.get("29431089")
    if row is None:
        pytest.skip("recording does not include account 29431089")
    assert row.balance is not None
    assert row.balance.amount == 3619868606.0


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("name", _EMPTY)
async def test_a_recorded_fail_open_body_is_an_empty_table_not_an_error(
    client: BackstopClient, name: str
) -> None:
    """A product id and a nonexistent id both return this. It must parse, and be empty."""
    result = await _replay(client, name)

    assert result.rows == ()
    assert result.all_count == 0
    assert result.source == "table-api"
