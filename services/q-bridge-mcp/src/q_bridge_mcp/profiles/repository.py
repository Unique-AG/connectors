from __future__ import annotations

from functools import lru_cache

from key_value.aio.protocols import AsyncKeyValue

from q_bridge_mcp.auth.storage import create_storage
from q_bridge_mcp.profiles.models import OrganizationCredentials, UserProfile

PROFILE_COLLECTION = "q-bridge-user-profiles"
ORGANIZATION_CREDENTIALS_COLLECTION = "q-bridge-organization-credentials"


class UserProfileRepository:
    def __init__(self, storage: AsyncKeyValue) -> None:
        self._storage: AsyncKeyValue = storage

    async def get(self, *, company_id: str, user_id: str) -> UserProfile:
        value = await self._storage.get(
            self._profile_key(company_id=company_id, user_id=user_id),
            collection=PROFILE_COLLECTION,
        )
        return UserProfile.model_validate(value or {})

    async def save(
        self,
        *,
        company_id: str,
        user_id: str,
        profile: UserProfile,
    ) -> None:
        await self._storage.put(
            self._profile_key(company_id=company_id, user_id=user_id),
            profile.model_dump(by_alias=True),
            collection=PROFILE_COLLECTION,
        )

    @staticmethod
    def _profile_key(*, company_id: str, user_id: str) -> str:
        return f"{company_id}:{user_id}"


class OrganizationCredentialsRepository:
    def __init__(self, storage: AsyncKeyValue) -> None:
        self._storage: AsyncKeyValue = storage

    async def get(self, *, company_id: str) -> OrganizationCredentials | None:
        value = await self._storage.get(
            company_id,
            collection=ORGANIZATION_CREDENTIALS_COLLECTION,
        )
        if value is None:
            return None
        return OrganizationCredentials.model_validate(value)

    async def save(
        self,
        *,
        company_id: str,
        credentials: OrganizationCredentials,
    ) -> None:
        await self._storage.put(
            company_id,
            credentials.model_dump(by_alias=True, mode="json"),
            collection=ORGANIZATION_CREDENTIALS_COLLECTION,
        )


@lru_cache(maxsize=1)
def get_profile_repository() -> UserProfileRepository:
    return UserProfileRepository(create_storage())


@lru_cache(maxsize=1)
def get_organization_credentials_repository() -> OrganizationCredentialsRepository:
    return OrganizationCredentialsRepository(create_storage())
