from __future__ import annotations

import logging
from functools import lru_cache
from typing import Protocol

from unique_sdk import (
    APIRequestor,
    AuthenticationError,
    InvalidRequestError,
)

from q_bridge_mcp.config.settings import settings
from q_bridge_mcp.profiles.models import OrganizationCredentials

logger = logging.getLogger(__name__)


class CredentialsValidator(Protocol):
    async def validate(
        self,
        *,
        credentials: OrganizationCredentials,
        user_id: str,
        company_id: str,
    ) -> None: ...


class UniqueCredentialsValidator:
    async def validate(
        self,
        *,
        credentials: OrganizationCredentials,
        user_id: str,
        company_id: str,
    ) -> None:
        requestor = APIRequestor(
            user_id=user_id,
            company_id=company_id,
            key=credentials.api_key,
            app_id=credentials.app_id,
        )
        requestor.api_base = str(settings.unique_api_base_url).rstrip("/")

        logger.info(
            "Validating organization credentials with the Unique Public API (user_id=%s, company_id=%s)",
            user_id,
            company_id,
        )
        try:
            _ = await requestor.request_async("get", f"/users/{user_id}")
        except (AuthenticationError, InvalidRequestError) as error:
            logger.warning(
                "Organization credential validation failed (error_type=%s, user_id=%s, company_id=%s)",
                type(error).__name__,
                user_id,
                company_id,
            )
            raise ValueError(
                "The app ID and API key are not valid for this organization"
            ) from error
        logger.info(
            "Organization credentials validated with the Unique Public API (user_id=%s, company_id=%s)",
            user_id,
            company_id,
        )


@lru_cache(maxsize=1)
def get_credentials_validator() -> CredentialsValidator:
    return UniqueCredentialsValidator()
