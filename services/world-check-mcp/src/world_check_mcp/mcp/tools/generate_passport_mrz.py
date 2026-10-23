from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.upstream import Upstream


@tool(
    title="Generate Passport MRZ",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def generate_passport_mrz(
    passport: Annotated[contexts.Passport, Field(description="Document details as printed.")],
    upstream: Upstream = Depends(get_upstream),
) -> contexts.Mrz:
    """Generate MRZ lines without creating a case or recording a verification.

    Issuing state and nationality come from get_reference_data nationalities. ICAO conformity
    does not prove authenticity, ownership, or validity.
    """
    try:
        return await contexts.generate_passport_mrz(upstream=upstream, passport=passport)
    except contexts.PassportError as error:
        raise ToolError(str(error)) from error
