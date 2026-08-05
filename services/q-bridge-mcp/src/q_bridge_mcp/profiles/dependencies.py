from __future__ import annotations

import logging
from dataclasses import dataclass

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError

from q_bridge_mcp.dependencies import get_company_id, get_user_id
from q_bridge_mcp.profiles.models import OrganizationCredentials, UserProfile
from q_bridge_mcp.profiles.repository import (
    OrganizationCredentialsRepository,
    UserProfileRepository,
    get_organization_credentials_repository,
    get_profile_repository,
)

logger = logging.getLogger(__name__)


class ConfigurationRequiredError(ToolError):
    def __init__(self, message: str) -> None:
        super().__init__(message, log_level=logging.INFO)


@dataclass(frozen=True)
class QBridgeConfiguration:
    profile: UserProfile
    credentials: OrganizationCredentials


async def require_configuration(
    profile_repository: UserProfileRepository = Depends(  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
        get_profile_repository
    ),
    credentials_repository: OrganizationCredentialsRepository = Depends(  # noqa: B008  # pyright: ignore[reportCallInDefaultInitializer]
        get_organization_credentials_repository
    ),
    user_id: str = Depends(get_user_id),  # pyright: ignore[reportCallInDefaultInitializer]
    company_id: str = Depends(get_company_id),  # pyright: ignore[reportCallInDefaultInitializer]
) -> QBridgeConfiguration:
    profile = await profile_repository.get(company_id=company_id, user_id=user_id)
    credentials = await credentials_repository.get(company_id=company_id)
    if profile.skills_root_folder is None or credentials is None:
        logger.info(
            "Blocked Q Bridge tool because setup is incomplete (user_id=%s, company_id=%s)",
            user_id,
            company_id,
        )
        raise ConfigurationRequiredError(
            "Q Bridge setup is incomplete. Open profile_settings before using this tool."
        )

    return QBridgeConfiguration(profile=profile, credentials=credentials)
