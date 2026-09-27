"""Institutional investors: resolving one by name, and the record behind it."""

from with_intelligence_mcp.features.investors.api_responses import (
    ClassificationAttributes,
    InvestorExtendedAttributes,
    InvestorListItemAttributes,
)
from with_intelligence_mcp.features.investors.dependencies import (
    get_investor_query_factory,
    get_map_investor_to_response_util_factory,
    get_resolve_investor_record_query_factory,
)
from with_intelligence_mcp.features.investors.fetch_investor import INVESTORS_PATH, fetch_investor
from with_intelligence_mcp.features.investors.queries import (
    GetInvestorQuery,
    ResolveInvestorRecordQuery,
)
from with_intelligence_mcp.features.investors.resolve_investor import resolve_investor
from with_intelligence_mcp.features.investors.resolve_investor_record import (
    InvestorRecordResolution,
    resolve_investor_record,
)
from with_intelligence_mcp.features.investors.resource_utils import MapInvestorToResponseUtil
from with_intelligence_mcp.features.investors.responses import (
    ConsultantResponse,
    InvestorAmbiguousResponse,
    InvestorCandidateResponse,
    InvestorNotEntitledResponse,
    InvestorNotFoundResponse,
    InvestorProfileResponse,
)
from with_intelligence_mcp.features.investors.search_investors_by_name import (
    search_investors_by_name,
)

__all__ = [
    "INVESTORS_PATH",
    "ClassificationAttributes",
    "ConsultantResponse",
    "GetInvestorQuery",
    "InvestorAmbiguousResponse",
    "InvestorCandidateResponse",
    "InvestorExtendedAttributes",
    "InvestorListItemAttributes",
    "InvestorNotEntitledResponse",
    "InvestorNotFoundResponse",
    "InvestorProfileResponse",
    "InvestorRecordResolution",
    "MapInvestorToResponseUtil",
    "ResolveInvestorRecordQuery",
    "fetch_investor",
    "get_investor_query_factory",
    "get_map_investor_to_response_util_factory",
    "get_resolve_investor_record_query_factory",
    "resolve_investor",
    "resolve_investor_record",
    "search_investors_by_name",
]
