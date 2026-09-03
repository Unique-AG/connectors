"""Fidelity: `GetHoldingsQuery.run` against a real recorded table payload.

Every other test in this feature builds its own JSON, which means a field Backstop renames — or an
alias that was wrong from the start — stays invisible: the fixture and the model are written from
the same mistaken assumption. These replay a response actually recorded from the live instance, so
the projection is checked against Backstop's real field names and nesting.

`recordings/` holds those responses with tenant data scrubbed — ids remapped, investor names and
account numbers replaced, amounts flattened, the host rewritten. Only the *shape* is under test, so
scrubbing costs nothing, and it means these run in CI: the unredacted originals live in the repo's
gitignored `docs/json/`, so a test that depended on them would silently skip everywhere it matters.

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
from backstop_mcp.features.accounts import HoldingListingDto, HoldingRowDto
from tests.features.accounts.conftest import make_get_holdings_query
from tests.helpers import BASE_URL

_RECORDINGS = Path(__file__).parent / "recordings"
_URL = f"{BASE_URL}/bsg-account-table-data"

_POPULATED = "bsg-account-table-data.json"
# What a product id or a nonexistent id returns: a 200 with an empty table.
_EMPTY = "bsg-account-table-data-empty.json"

# The one row given a distinctive balance, so a wrong `balance` alias fails loudly here.
_CANARY_ACCOUNT = "10000999"
_CANARY_BALANCE = 3619868606.0


def _recorded_body(name: str) -> dict[str, object]:
    """A scrubbed recording. Committed, so this never degrades into a skip."""
    path = _RECORDINGS / name
    assert path.is_file(), f"expected recording {path}"
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


async def _replay(client: BackstopClient, name: str, **kwargs: bool) -> HoldingListingDto:
    respx.get(_URL).mock(return_value=httpx.Response(200, json=_recorded_body(name)))
    return await make_get_holdings_query(client).run(owner_id="recording", **kwargs)


@pytest.mark.asyncio
@respx.mock
async def test_a_recorded_table_projects_every_row(client: BackstopClient) -> None:
    """No row is dropped, and Backstop's own counts agree with the rows it sent."""
    result = await _replay(client, _POPULATED, include_closed=True)

    assert result.rows, "recording has no rows to check"
    assert result.rows_dropped == 0
    assert len(result.rows) == result.all_count


@pytest.mark.asyncio
@respx.mock
async def test_every_projected_field_is_populated_somewhere(client: BackstopClient) -> None:
    """A field nothing ever populates is the signature of a wrong alias.

    Verified to catch a broken alias on `percentageOfProduct`, `otherId` and `fundedDate`. It
    cannot catch one on `balance`, `commitment`, `closed`, `investor`, `account`, `product` or
    `organization`: `populate_by_name=True` means a field whose Python name already equals the
    wire key is still populated by name when its alias is wrong — so those aliases are unbreakable
    rather than untested.

    The exclusions are fields genuinely empty for every account on this tenant (`"-"` commitments,
    a zero share of master) or only ever set on the fallback path — their absence here says
    nothing about the alias. Everything else must be non-`None` on at least one recorded row.
    """
    result = await _replay(client, _POPULATED, include_closed=True)

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
async def test_the_recorded_balance_matches_the_documented_series(client: BackstopClient) -> None:
    """The claim the whole primary path rests on.

    The figure is the one measured live against `/accounts/{id}/values` and recorded in the
    design doc: this endpoint's balance is the newest point of the documented series. A wrong
    `balance` alias would make this `None` while every hand-written test still passed.
    """
    result = await _replay(client, _POPULATED, include_closed=True)
    rows = {row.account_id: row for row in result.rows}

    row = rows[_CANARY_ACCOUNT]
    assert row.balance is not None
    assert row.balance.amount == _CANARY_BALANCE


@pytest.mark.asyncio
@respx.mock
async def test_a_recorded_fail_open_body_is_an_empty_table_not_an_error(
    client: BackstopClient,
) -> None:
    """A product id and a nonexistent id both return this. It must parse, and be empty."""
    result = await _replay(client, _EMPTY)

    assert result.rows == ()
    assert result.all_count == 0
    assert result.source == "table-api"
