"""MCP-facing account and product shapes for the two positions tools.

Split across three modules but re-exported as one surface: `shared` holds the account row, the
closed-account hint, and the figure shape both tools read from; `product_positions` and
`party_accounts` hold each tool's own resolved-response shape. A caller comparing
`get_product_positions` to `get_accounts_for_party` is reading one vocabulary.
"""

from backstop_mcp.features.accounts.responses.party_accounts import (
    PartyAccountsResolvedResponse,
    party_accounts_response,
)
from backstop_mcp.features.accounts.responses.product_positions import (
    ProductAmbiguousResponse,
    ProductCandidateResponse,
    ProductPositionsResolvedResponse,
    product_candidate_response,
    product_positions_response,
    unresolved_product_response,
)
from backstop_mcp.features.accounts.responses.shared import (
    AccountRowResponse,
    FigureResponse,
    InvestorQualificationResponse,
    InvestorTypeResponse,
    OwnerResponse,
    PositionRowResponse,
    ProductRefResponse,
    SeriesErrorResponse,
    UnvaluedPointResponse,
    account_row_response,
    closed_hint,
    figure_response,
    investor_qualification_response,
    investor_type_response,
    owner_response,
    position_row_response,
    product_ref_response,
)

__all__ = [
    "AccountRowResponse",
    "FigureResponse",
    "InvestorQualificationResponse",
    "InvestorTypeResponse",
    "OwnerResponse",
    "PartyAccountsResolvedResponse",
    "PositionRowResponse",
    "ProductAmbiguousResponse",
    "ProductCandidateResponse",
    "ProductPositionsResolvedResponse",
    "ProductRefResponse",
    "SeriesErrorResponse",
    "UnvaluedPointResponse",
    "account_row_response",
    "closed_hint",
    "figure_response",
    "investor_qualification_response",
    "investor_type_response",
    "owner_response",
    "party_accounts_response",
    "position_row_response",
    "product_candidate_response",
    "product_positions_response",
    "product_ref_response",
    "unresolved_product_response",
]
