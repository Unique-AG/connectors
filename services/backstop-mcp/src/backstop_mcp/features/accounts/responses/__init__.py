"""MCP-facing account and product shapes.

Split across modules but re-exported as one surface: `shared` holds the account row, product
resolution, and the closed-account hint; `party_accounts`, `product_investors`,
`capital_flows`, `product`, and `time_series` hold each shipped tool's resolved-response shape.
"""

from backstop_mcp.features.accounts.responses.capital_flows import (
    MAX_CAPITAL_FLOW_SCAN_RECORDS,
    CapitalFlowPartyResponse,
    CapitalFlowRowResponse,
    CapitalFlowsResolvedResponse,
)
from backstop_mcp.features.accounts.responses.party_accounts import (
    HoldingFigureErrorResponse,
    HoldingRowResponse,
    MoneyResponse,
    PartyAccountsResolvedResponse,
    ShareResponse,
)
from backstop_mcp.features.accounts.responses.product import (
    ProductDescriptionResponse,
    ProductRecordResponse,
    ProductResolvedResponse,
    ProductRiskFreeRateResponse,
)
from backstop_mcp.features.accounts.responses.product_investors import (
    InvestorHoldingResponse,
    InvestorResponse,
    ProductAccountsResponse,
    ProductInvestorsResolvedResponse,
    ProductListingResponse,
    ValueTotalResponse,
    investors_from_listings,
)
from backstop_mcp.features.accounts.responses.shared import (
    AccountRowResponse,
    InvestorQualificationResponse,
    InvestorTypeResponse,
    LatestValueResponse,
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
    "MAX_CAPITAL_FLOW_SCAN_RECORDS",
    "AccountRowResponse",
    "CapitalFlowPartyResponse",
    "CapitalFlowRowResponse",
    "CapitalFlowsResolvedResponse",
    "HoldingFigureErrorResponse",
    "HoldingRowResponse",
    "InvestorHoldingResponse",
    "InvestorQualificationResponse",
    "InvestorResponse",
    "InvestorTypeResponse",
    "LatestValueResponse",
    "MoneyResponse",
    "OwnerResponse",
    "PartyAccountsResolvedResponse",
    "ProductAmbiguousResponse",
    "ProductCandidateResponse",
    "ProductInvestorsResolvedResponse",
    "ProductAccountsResponse",
    "ProductListingResponse",
    "ProductDescriptionResponse",
    "ProductRecordResponse",
    "ProductRiskFreeRateResponse",
    "ProductResolvedResponse",
    "ProductRefResponse",
    "ShareResponse",
    "TimeSeriesPointResponse",
    "TimeSeriesResolvedResponse",
    "closed_hint",
    "ValueTotalResponse",
    "investors_from_listings",
]
