"""Registered MCP tools."""

from collections.abc import Awaitable, Callable

from with_intelligence_mcp.features.articles.tools.get_articles import get_articles
from with_intelligence_mcp.features.consultants.tools.get_consultant import get_consultant
from with_intelligence_mcp.features.funds.tools.get_fund import get_fund
from with_intelligence_mcp.features.intentions.tools.get_intentions import get_intentions
from with_intelligence_mcp.features.investments.tools.get_investments import get_investments
from with_intelligence_mcp.features.investors.tools.get_investor import get_investor
from with_intelligence_mcp.features.managers.tools.get_manager import get_manager
from with_intelligence_mcp.features.mandates.tools.get_mandates import get_mandates
from with_intelligence_mcp.features.persons.tools.get_people_for_investor import (
    get_people_for_investor,
)

type ToolFunction = Callable[..., Awaitable[object]]

TOOLS: tuple[ToolFunction, ...] = (
    get_investor,
    get_people_for_investor,
    get_investments,
    get_mandates,
    get_intentions,
    get_articles,
    get_fund,
    get_manager,
    get_consultant,
)
