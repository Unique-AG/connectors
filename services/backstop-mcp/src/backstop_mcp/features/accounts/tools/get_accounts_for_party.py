"""`get_accounts_for_party`: what a person or organization holds, with balances.

Reads Backstop's undocumented account-table endpoint first — one request for the whole table,
figures included — and falls back to the documented `/accounts` walk plus per-account series when
that fails. `fetch_holdings` owns that choice; this module owns the tool contract and one thing
the fetch layer cannot do.

That one thing is the fail-open hole. The table endpoint answers `200` with an empty table for a
nonexistent id, for a wrong-typed id, and for a party that genuinely owns nothing — three cases it
cannot distinguish. A tool that relayed the first two as "owns nothing" would be confidently wrong
about the question this tool exists to answer. So when the answer *would* be "owns nothing" and the
party id was never confirmed against Backstop, the party is verified before that is reported. It
costs one request, only on the branch where being wrong is silent.
"""

import logging
from collections.abc import Sequence
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.accounts import (
    PartyAccountsResolvedResponse,
    fetch_holdings,
)
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyDto,
    ResolvedPartyResponse,
    fetch_party_name,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)

type GetAccountsForPartyResponse = (
    PartyAmbiguousResponse | NotFoundResponse | PartyAccountsResolvedResponse
)


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetAccountsForPartyResponse),
)
async def get_accounts_for_party(
    ctx: Context,
    search_type: Annotated[
        SearchType,
        Field(
            description=(
                "Which Backstop collection to resolve the party against — fold the caller's "
                "wording to one of the four. A company, firm, fund, institution, or manager is "
                "`organizations`; any human is `people`. Pick `contacts` or `employees` only "
                "when a prior resolve echoed one (echo it back — a contact or employee id is "
                "not a people id) or the caller clearly means an internal staff member."
            ),
        ),
    ],
    party_id: Annotated[
        str | None,
        Field(
            description=(
                "Trusted Backstop Party ID from a prior resolve echo (`id` / `search_type` / "
                "`name`). Never invent or guess. Exactly one of `party_id` or `search` must be "
                "provided."
            ),
        ),
    ] = None,
    search: Annotated[
        str | None,
        Field(
            description=(
                "Name or email to resolve when no trusted `party_id` is available. Exactly one "
                "of `party_id` or `search` must be provided."
            ),
        ),
    ] = None,
    include_closed: Annotated[
        bool,
        Field(
            description=(
                "When false (default), only open accounts are returned (`closedDate` key "
                "absent). Pass true to include closed accounts."
            ),
        ),
    ] = False,
    client: BackstopClient = Depends(get_backstop_client),
) -> GetAccountsForPartyResponse:
    """What a person or organization holds: their accounts, with balances, across products.

    Pass `search_type` plus a trusted `party_id` (from a prior resolve echo — never invent one) or
    `search`. Ownership is the account's owner, not its name: ACCOUNT quick-search matches names
    and will miss a differently named vehicle.

    The primary path is Backstop's undocumented UI table-data endpoint and may 404 on another
    tenant — that is not "holds nothing". This tool then falls back internally to the documented
    `/accounts` walk; `data_caveat` (`fallback_note`) lists the fields that path omits. Each row
    carries the account and product ids, tenure dates, and the snapshot figures —
    `balance`, `commitment`, `unfunded_commitment`, share of product and of master. This answers
    "how much does X have in fund Y", "summarise X's investments", and "how long have they been
    in Y" in one call.

    **Read `data_caveat` before quoting a figure.** Two endpoints can answer this, and they differ
    in what they know: the fast one publishes a balance with no as-of date and no
    ACTUAL/ESTIMATE label, the fallback publishes fewer fields but dates its figures. `source`
    says which one answered. A dated, labelled NAV is `get_time_series` on that account's
    `values`, not this listing.

    A missing figure is omitted, never zeroed. `figure_errors` on a row distinguishes "the request
    failed" from "Backstop publishes no number".

    Tenants may call a product a fund, vehicle, or share class; the Backstop name is still
    `product`. An empty list with `closed_omitted>0` means every owned account is closed — pass
    `include_closed=true` rather than reading that as "owns nothing".
    """
    result = await resolve_party(
        ctx,
        client,
        search_type=search_type,
        party_id=party_id,
        search=search,
    )
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)

    party = result.value
    logger.info(
        "accounts.for_party.start",
        extra={
            "segment": party.search_type,
            "entity_id": party.id,
            "include_closed": include_closed,
        },
    )
    listing = await fetch_holdings(client, owner_id=party.id, include_closed=include_closed)
    if _would_report_owns_nothing(listing.rows, listing.closed_omitted) and party.name is None:
        confirmed = await _confirm_party(client, party)
        if confirmed is None:
            logger.info(
                "accounts.for_party.unverified_party_id",
                extra={"segment": party.search_type, "entity_id": party.id},
            )
            # `NotFoundResponse` is the shared shape and carries no free-text field; the
            # reason this check ran at all is in the module docstring and the log line above.
            return NotFoundResponse(query=party.id, scope=party.search_type)
        party = confirmed
    logger.info(
        "accounts.for_party.completed",
        extra={
            "segment": party.search_type,
            "entity_id": party.id,
            "source": listing.source,
            "returned": len(listing.rows),
            "closed_omitted": listing.closed_omitted,
            "rows_dropped": listing.rows_dropped,
        },
    )
    return PartyAccountsResolvedResponse.from_holdings(
        listing, resolved=ResolvedPartyResponse.from_party(party)
    )


def _would_report_owns_nothing(rows: Sequence[object], closed_omitted: int) -> bool:
    """True when the payload says "nothing", with no closed accounts to explain it away."""
    return not rows and closed_omitted == 0


async def _confirm_party(
    client: BackstopClient, party: ResolvedPartyDto
) -> ResolvedPartyDto | None:
    """The party with its name filled in, or `None` when Backstop has no such record.

    Only reached on the empty-holdings branch for an unconfirmed id, so the extra request is
    never on the path of an answer that already has content. A non-404 failure is left to
    propagate: "we could not check" must not be reported as "no such party".
    """
    try:
        name = await fetch_party_name(client, search_type=party.search_type, party_id=party.id)
    except BackstopApiError as exc:
        if exc.status_code == 404:
            return None
        raise
    return ResolvedPartyDto(id=party.id, search_type=party.search_type, name=name)
