"""`get_product_investors` response: a product's accounts and owners, no figures."""

from typing import Literal, Self

from pydantic import Field

from backstop_mcp.features.accounts.internal_dto import AccountListingDto, ResolvedProductDto
from backstop_mcp.features.accounts.responses.shared import (
    AccountRowResponse,
    ProductRefResponse,
    closed_hint,
)
from backstop_mcp.models import OmitNoneModel


class ProductInvestorsResolvedResponse(OmitNoneModel):
    """The accounts in one product, with owners. Dated figures are a later `get_time_series`."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the product was found and its accounts listed.",
    )
    product: ProductRefResponse = Field(
        description=(
            "The product these accounts belong to. Echo `id` as `entity_id` with "
            "`entity_type='products'` on `get_time_series` for fund-level AUM — never invent one."
        )
    )
    accounts: tuple[AccountRowResponse, ...] = Field(
        description=(
            "Investor vehicles in this product. Echo each `id` as `entity_id` with "
            "`entity_type='accounts'` on `get_time_series` for a dated figure."
        )
    )
    closed_omitted: int = Field(
        description=(
            "How many accounts were dropped because `include_closed` is false. Distinguishes "
            "a product with no investors from one whose accounts are all closed."
        )
    )
    include_closed_hint: str | None = Field(
        default=None,
        description=(
            "Set when closed accounts were omitted. Pass `include_closed=true` rather than "
            "treating an empty list as 'this product has no investors'."
        ),
    )

    @classmethod
    def from_listing(cls, listing: AccountListingDto, *, product: ResolvedProductDto) -> Self:
        accounts = tuple(AccountRowResponse.from_record(account) for account in listing.accounts)
        return cls(
            product=ProductRefResponse.from_product(product),
            accounts=accounts,
            closed_omitted=listing.closed_omitted,
            include_closed_hint=closed_hint(
                closed_omitted=listing.closed_omitted,
                returned=len(accounts),
                subject="product",
            ),
        )
