"""`get_product_positions`-specific response shape, built on the shared account/figure
vocabulary.
"""

from typing import Literal, Self

from pydantic import Field

from backstop_mcp.features.accounts.internal_dto import ProductPositionsDto, ResolvedProductDto
from backstop_mcp.features.accounts.responses.shared import (
    FigureResponse,
    PositionRowResponse,
    ProductRefResponse,
    closed_hint,
)
from backstop_mcp.features.resolution import (
    AmbiguousResponse,
    Candidate,
    CandidateResponse,
    NotFoundResponse,
    Unresolved,
    unresolved_response,
)
from backstop_mcp.models import OmitNoneModel


class ProductCandidateResponse(CandidateResponse):
    """One ambiguous product match. Echo `id` as `product_id` — never invent one."""

    key: str = Field(
        description=(
            "Stable identity for this candidate. Echo it only as part of picking this option "
            "— it is not a Backstop product id."
        )
    )
    label: str = Field(
        description=(
            "What to show the user when asking which product they meant, usually "
            "'Name (SHORT)' — e.g. 'Capstone Global Unconstrained Portfolio (CGUP)'."
        )
    )
    id: str = Field(
        description=(
            "Backstop product id. Echo it as `product_id` on the next call — never invent one."
        )
    )
    name: str | None = Field(
        default=None,
        description="Product name as Backstop stores it. Omitted when the index had none.",
    )
    short_name: str | None = Field(
        default=None,
        description="`productShortName` (e.g. 'CGUP'). Omitted when the product has none.",
    )

    @classmethod
    def from_candidate(cls, candidate: Candidate[ResolvedProductDto]) -> Self:
        product = candidate.value
        return cls(
            key=candidate.key,
            label=candidate.label,
            id=product.id,
            name=product.name,
            short_name=product.short_name,
        )


class ProductAmbiguousResponse(AmbiguousResponse[ProductCandidateResponse]):
    """Returned when more than one product matched and none was chosen.

    Show each candidate's `label` to the user, then retry with that `id` as `product_id`.
    """

    scope: str = Field(
        description="Collection the query was resolved against. Always 'products' for this tool."
    )
    candidates: list[ProductCandidateResponse] = Field(
        default_factory=list,
        description=(
            "The matching products. Show `label` to the user, then retry with that "
            "candidate's `id` as `product_id` — never invent one."
        ),
    )

    @classmethod
    def from_unresolved(cls, result: Unresolved[ResolvedProductDto]) -> Self | NotFoundResponse:
        return unresolved_response(
            result,
            ambiguous_model=cls,
            to_candidate=ProductCandidateResponse.from_candidate,
        )


class ProductPositionsResolvedResponse(OmitNoneModel):
    """`get_product_positions` after the product was found and its accounts fetched.

    An empty `accounts` list with `closed_omitted=0` means the product has no accounts. An empty
    list with `closed_omitted>0` means every account is closed — read `include_closed_hint`.
    """

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the product was found and its accounts fetched.",
    )
    product: ProductRefResponse = Field(
        description=(
            "The product this call settled on. Echo `id` as `product_id` later — never invent one."
        )
    )
    accounts: tuple[PositionRowResponse, ...] = Field(
        description=(
            "Positions in this product. Each figure is `{value, date, valueStatus?}` from "
            "`values` (balance), `totalInvested`, and `totalRedemptions`. Omitted figures "
            "had no points, not a zero."
        )
    )
    closed_omitted: int = Field(
        description=(
            "How many matching accounts were dropped because `include_closed` is false. "
            "Distinguishes a product with no accounts from one whose accounts are all closed."
        )
    )
    accounts_omitted: int = Field(
        default=0,
        description=(
            "How many open accounts were listed but returned without figures because this "
            "product exceeds the per-call fan-out cap. Greater than zero means `accounts` is a "
            "partial list and `balance_total` is a partial sum — say so rather than totalling "
            "them as if complete."
        ),
    )
    aum: FigureResponse | None = Field(
        default=None,
        description=(
            "Latest assets under management (AUM) for the product: the product's total reported "
            "value, not one investor's balance. From `/products/{id}/aums`. Omitted when none "
            "was found."
        ),
    )
    balance_total: float | None = Field(
        default=None,
        description=(
            "Sum of the balances in `accounts`. Accounts whose `values` series had no number "
            "are left out rather than counted as zero, and balances are summed without currency "
            "conversion. Omitted when no account returned a balance."
        ),
    )
    aum_difference: float | None = Field(
        default=None,
        description=(
            "`balance_total` minus `aum`: positive means the returned balances add up to more "
            "than the product's reported total. Omitted when either side is missing."
        ),
    )
    aum_diverges: bool = Field(
        description=(
            "True when `aum_difference` exceeds 0.5% of assets under management (AUM). The open "
            "default excludes closed-but-still-valued accounts, so a small gap is normal — this "
            "is a tolerance verdict, not a failure. Weigh `aum_difference` yourself before "
            "reporting a mismatch."
        )
    )
    include_closed_hint: str | None = Field(
        default=None,
        description=(
            "Set when closed accounts were omitted. Tells the caller to pass "
            "`include_closed=true` rather than treating an empty list as 'no investors'."
        ),
    )

    @classmethod
    def from_positions(cls, result: ProductPositionsDto) -> Self:
        reconciliation = result.reconciliation
        return cls(
            product=ProductRefResponse.from_product(result.product),
            accounts=tuple(
                PositionRowResponse.from_position(position) for position in result.accounts
            ),
            closed_omitted=result.closed_omitted,
            accounts_omitted=result.accounts_omitted,
            aum=FigureResponse.from_figure(result.aum),
            balance_total=reconciliation.balance_total,
            aum_difference=reconciliation.difference,
            aum_diverges=reconciliation.diverges,
            include_closed_hint=closed_hint(
                closed_omitted=result.closed_omitted,
                returned=len(result.accounts),
                subject="product",
            ),
        )
