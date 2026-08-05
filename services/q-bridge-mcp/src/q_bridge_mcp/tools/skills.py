from __future__ import annotations

import base64
import logging
from typing import Any

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool

from q_bridge_mcp.dependencies import get_company_id, get_user_id
from q_bridge_mcp.profiles.dependencies import ConfigurationRequiredError
from q_bridge_mcp.skills.service import CatalogAccessor, get_catalog_accessor

logger = logging.getLogger(__name__)


@tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def get_skill_guide(
    skill: str | None = None,
    file: str | None = None,
    force_refresh: bool = False,
    accessor: CatalogAccessor = Depends(  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
        get_catalog_accessor
    ),
    user_id: str = Depends(get_user_id),  # pyright: ignore[reportCallInDefaultInitializer]
    company_id: str = Depends(get_company_id),  # pyright: ignore[reportCallInDefaultInitializer]
) -> dict[str, Any]:
    """Run the mandatory Q Bridge skill preflight and read a skill resource.

    Call without a skill before answering a user request to discover available
    skills. Pass a skill to list its files, then pass both skill and file to
    read one file. Set force_refresh to bypass and replace the authenticated
    user's cached skill catalog.
    """
    if skill is None:
        logger.info(
            "Discovering Q Bridge skills (user_id=%s, company_id=%s)",
            user_id,
            company_id,
        )
    elif file is None:
        logger.info(
            "Listing files for a Q Bridge skill (user_id=%s, company_id=%s)",
            user_id,
            company_id,
        )
    else:
        logger.info(
            "Reading a Q Bridge skill file (user_id=%s, company_id=%s)",
            user_id,
            company_id,
        )

    try:
        catalog = await accessor.get_catalog(force_refresh=force_refresh)
    except ConfigurationRequiredError:
        raise
    except Exception as error:
        logger.warning(
            "Unable to load Q Bridge skills (error_type=%s, user_id=%s, company_id=%s)",
            type(error).__name__,
            user_id,
            company_id,
        )
        raise ToolError(
            "Unable to load Q Bridge skills. Try again later.",
            log_level=logging.WARNING,
        ) from error

    if skill is None:
        if file is not None:
            raise ToolError("file requires skill", log_level=logging.INFO)
        logger.info(
            "Discovered Q Bridge skills (skill_count=%d, user_id=%s, company_id=%s)",
            len(catalog.skills),
            user_id,
            company_id,
        )
        return {
            "success": True,
            "skills": [
                {
                    "name": available_skill.name,
                    "description": available_skill.description,
                    "uri": f"skill://{available_skill.name}/SKILL.md",
                }
                for available_skill in catalog.skills.values()
            ],
            "howToUse": (
                "Select relevant skills from this list, then call "
                "get_skill_guide(skill='<name>', file='SKILL.md') before "
                "answering. Resource-capable clients may read the listed "
                "skill:// URIs directly instead."
            ),
            "requiredNextStep": (
                "Read the SKILL.md for every skill relevant to the user's "
                "request before answering."
            ),
        }

    available_skill = catalog.skills.get(skill)
    if available_skill is None:
        raise ToolError("Requested skill is not available", log_level=logging.INFO)
    if file is None:
        return {
            "success": True,
            "skill": skill,
            "uri": f"skill://{skill}/SKILL.md",
            "files": [
                {
                    "path": skill_file.path,
                    "uri": f"skill://{skill}/{skill_file.path}",
                    "mimeType": skill_file.mime_type,
                    "size": skill_file.size,
                    "hash": skill_file.hash,
                }
                for skill_file in available_skill.files.values()
            ],
        }

    skill_file = available_skill.files.get(file)
    if skill_file is None:
        raise ToolError(
            "Requested skill file is not available",
            log_level=logging.INFO,
        )

    try:
        content = skill_file.content.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        content = base64.b64encode(skill_file.content).decode("ascii")
        encoding = "base64"

    return {
        "success": True,
        "skill": skill,
        "file": file,
        "uri": f"skill://{skill}/{file}",
        "mimeType": skill_file.mime_type,
        "encoding": encoding,
        "content": content,
    }
