from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from unique_sdk import (
    APIRequestor,
    AuthenticationError,
    InvalidRequestError,
)

from q_bridge_mcp.config.settings import settings
from q_bridge_mcp.profiles.models import OrganizationCredentials


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

        try:
            _ = await requestor.request_async("get", f"/users/{user_id}")
        except (AuthenticationError, InvalidRequestError) as error:
            raise ValueError(
                "The app ID and API key are not valid for this organization"
            ) from error


@lru_cache(maxsize=1)
def get_credentials_validator() -> CredentialsValidator:
    return UniqueCredentialsValidator()
