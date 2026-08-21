"""MCP-facing account and product shapes for the two positions tools.

Split across three modules but re-exported as one surface: `shared` holds the account row, the
closed-account hint, and the figure shape both tools read from; `product_positions` and
`party_accounts` hold each tool's own resolved-response shape. A caller comparing
`get_product_positions` to `get_accounts_for_party` is reading one vocabulary.
"""

from backstop_mcp.features.accounts.responses.party_accounts import PartyAccountsResolvedResponse
from backstop_mcp.features.accounts.responses.product_positions import (
    ProductAmbiguousResponse,
    ProductCandidateResponse,
    ProductPositionsResolvedResponse,
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
    closed_hint,
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
    "closed_hint",
]
