"""The one declaration of which tools this server exposes.

`create_app` registers from this list. A tool module that exists but is not listed here fails
`tests/test_layering.py` rather than shipping unreachable.
"""

from collections.abc import Awaitable, Callable

from with_intelligence_mcp.features.investments.tools.get_investments import get_investments
from with_intelligence_mcp.features.investors.tools.get_investor import get_investor
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
)
