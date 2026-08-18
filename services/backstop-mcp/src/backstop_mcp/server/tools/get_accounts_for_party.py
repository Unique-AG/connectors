"""`get_accounts_for_party`: which accounts a person or organization owns, across products.

Listing and status only — no series fan-out. `filter[owner]` is 400, so this walks `/accounts`
and keeps `relationships.owner` linkage id == the resolved party id.
"""

import logging
from typing import Annotated, Literal

from fastmcp import Context
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.accounts import (
    AccountListing,
    AccountRowResponse,
    account_row_response,
    fetch_accounts_for_party,
)
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyResponse,
    party_response,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import OmitNoneModel, published_output_schema
from backstop_mcp.server.runtime import get_backstop_client

logger = logging.getLogger(__name__)


class PartyAccountsResolvedResponse(OmitNoneModel):
    """`get_accounts_for_party` after the party was found and its accounts listed.

    Listing and status only — no series fan-out. An empty `accounts` list with
    `closed_omitted>0` means every owned account is closed.
    """

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the party was found and its accounts listed.",
    )
    resolved: ResolvedPartyResponse = Field(
        description=(
            "The identity this call settled on. Echo `id` / `search_type` / `name` as "
            "`party_id` later — never invent them."
        )
    )
    accounts: tuple[AccountRowResponse, ...] = Field(
        description=(
            "Accounts this party owns, across products. Each row includes the product "
            "`{id, name, short_name}` from the include. No balances or series."
        )
    )
    closed_omitted: int = Field(
        description=(
            "How many owned accounts were dropped because `include_closed` is false. "
            "Distinguishes a party with no accounts from one whose accounts are all closed."
        )
    )
    include_closed_hint: str | None = Field(
        default=None,
        description=(
            "Set when closed accounts were omitted. Pass `include_closed=true` rather than "
            "treating an empty list as 'this party owns nothing'."
        ),
    )


type GetAccountsForPartyResponse = (
    PartyAmbiguousResponse | NotFoundResponse | PartyAccountsResolvedResponse
)


def _resolved_response(
    *, resolved: ResolvedPartyResponse, listing: AccountListing
) -> PartyAccountsResolvedResponse:
    hint = None
    if listing.closed_omitted and not listing.accounts:
        hint = (
            "This party has accounts, but all of them are closed. Pass include_closed=true "
            "to list them."
        )
    elif listing.closed_omitted:
        hint = (
            f"{listing.closed_omitted} closed account(s) were omitted. Pass include_closed=true "
            "to include them."
        )
    return PartyAccountsResolvedResponse(
        resolved=resolved,
        accounts=tuple(account_row_response(account) for account in listing.accounts),
        closed_omitted=listing.closed_omitted,
        include_closed_hint=hint,
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
) -> GetAccountsForPartyResponse:
    """List the accounts a person or organization owns, across products.

    Pass `search_type` plus a trusted `party_id` (from a prior resolve echo — never invent one)
    or `search`. Ownership is `owner.id` on `/accounts`, not account name: ACCOUNT quick-search
    matches names and will miss a differently named vehicle.

    Each row is account identity, owner, status, and the product `{id, name, short_name}`.
    There is no series fan-out — for balances use `get_product_positions` with that product id.

    Tenants may call a product a fund, vehicle, or share class; the Backstop name is still
    `product`. An empty list with `closed_omitted>0` means every owned account is closed —
    pass `include_closed=true` rather than reading that as "owns nothing".
    """
    client = await get_backstop_client()
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
    listing = await fetch_accounts_for_party(
        client, owner_id=party.id, include_closed=include_closed
    )
    logger.info(
        "accounts.for_party.completed",
        extra={
            "segment": party.search_type,
            "entity_id": party.id,
            "returned": len(listing.accounts),
            "closed_omitted": listing.closed_omitted,
        },
    )
    return _resolved_response(resolved=party_response(party), listing=listing)
