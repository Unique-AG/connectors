"""`get_accounts_for_party`-specific response shape, built on the shared account/figure
vocabulary.
"""

from typing import Literal

from pydantic import Field

from backstop_mcp.features.accounts.internal_dto import AccountListingDto
from backstop_mcp.features.accounts.responses.shared import (
    AccountRowResponse,
    account_row_response,
    closed_hint,
)
from backstop_mcp.features.party_resolver import ResolvedPartyResponse
from backstop_mcp.models import OmitNoneModel


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


def party_accounts_response(
    *, resolved: ResolvedPartyResponse, listing: AccountListingDto
) -> PartyAccountsResolvedResponse:
    return PartyAccountsResolvedResponse(
        resolved=resolved,
        accounts=tuple(account_row_response(account) for account in listing.accounts),
        closed_omitted=listing.closed_omitted,
        include_closed_hint=closed_hint(
            closed_omitted=listing.closed_omitted,
            returned=len(listing.accounts),
            subject="party",
        ),
    )
