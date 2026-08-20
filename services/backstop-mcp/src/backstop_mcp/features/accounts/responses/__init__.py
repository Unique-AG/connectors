"""MCP-facing account and product shapes.

Split across modules but re-exported as one surface: `shared` holds the account row (the
`get_product_investors` listing, no figures), product resolution, and the closed-account
hint; `party_accounts` and `time_series` hold each shipped tool's resolved-response shape.
"""

from backstop_mcp.features.accounts.responses.party_accounts import (
    HoldingFigureErrorResponse,
    HoldingRowResponse,
    MoneyResponse,
    PartyAccountsResolvedResponse,
    ShareResponse,
)
from backstop_mcp.features.accounts.responses.shared import (
    AccountRowResponse,
    InvestorQualificationResponse,
    InvestorTypeResponse,
    OwnerResponse,
    ProductAmbiguousResponse,
    ProductCandidateResponse,
    ProductRefResponse,
    closed_hint,
)
from backstop_mcp.features.accounts.responses.time_series import (
    TimeSeriesPointResponse,
    TimeSeriesResolvedResponse,
)

__all__ = [
    "AccountRowResponse",
    "HoldingFigureErrorResponse",
    "HoldingRowResponse",
    "InvestorQualificationResponse",
    "InvestorTypeResponse",
    "MoneyResponse",
    "OwnerResponse",
    "PartyAccountsResolvedResponse",
    "ProductAmbiguousResponse",
    "ProductCandidateResponse",
    "ProductRefResponse",
    "ShareResponse",
    "TimeSeriesPointResponse",
    "TimeSeriesResolvedResponse",
    "closed_hint",
]
