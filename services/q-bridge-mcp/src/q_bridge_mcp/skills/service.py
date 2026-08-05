from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Protocol, final

from fastmcp.server.dependencies import get_access_token

from q_bridge_mcp.config.settings import settings
from q_bridge_mcp.dependencies import get_company_id, get_user_id
from q_bridge_mcp.profiles.dependencies import ConfigurationRequiredError
from q_bridge_mcp.profiles.models import OrganizationCredentials
from q_bridge_mcp.profiles.repository import (
    OrganizationCredentialsRepository,
    UserProfileRepository,
    get_organization_credentials_repository,
    get_profile_repository,
)
from q_bridge_mcp.skills.catalog import (
    CatalogCacheKey,
    SkillCatalog,
    SkillCatalogCache,
    build_skill_catalog,
)
from q_bridge_mcp.skills.client import KnowledgeBaseClient, UniqueKnowledgeBaseClient

logger = logging.getLogger(__name__)


class CatalogAccessor(Protocol):
    async def get_catalog(
        self,
        *,
        force_refresh: bool = False,
    ) -> SkillCatalog: ...


class CatalogPrewarmer(Protocol):
    async def prewarm(self, *, user_id: str, company_id: str) -> bool: ...


ClientFactory = Callable[
    [str, str, OrganizationCredentials],
    KnowledgeBaseClient,
]


def create_knowledge_base_client(
    user_id: str,
    company_id: str,
    credentials: OrganizationCredentials,
) -> KnowledgeBaseClient:
    return UniqueKnowledgeBaseClient.create(
        user_id=user_id,
        company_id=company_id,
        credentials=credentials,
    )


@final
class SkillCatalogService:
    def __init__(
        self,
        *,
        profile_repository: UserProfileRepository,
        credentials_repository: OrganizationCredentialsRepository,
        cache: SkillCatalogCache,
        client_factory: ClientFactory = create_knowledge_base_client,
    ) -> None:
        self._profile_repository = profile_repository
        self._credentials_repository = credentials_repository
        self._cache = cache
        self._client_factory = client_factory

    async def get_catalog(
        self,
        *,
        user_id: str,
        company_id: str,
        force_refresh: bool = False,
    ) -> SkillCatalog:
        profile = await self._profile_repository.get(
            company_id=company_id,
            user_id=user_id,
        )
        credentials = await self._credentials_repository.get(company_id=company_id)
        if profile.skills_root_folder is None or credentials is None:
            raise ConfigurationRequiredError(
                "Q Bridge setup is incomplete. Open profile_settings before loading skills."
            )

        root_folder = profile.skills_root_folder.strip("/")
        key = CatalogCacheKey(
            company_id=company_id,
            user_id=user_id,
            root_folder=root_folder,
            credentials_version=credentials.updated_at.isoformat(),
        )

        async def load() -> SkillCatalog:
            client = self._client_factory(user_id, company_id, credentials)
            return await build_skill_catalog(
                client,
                root_folder=root_folder,
                user_id=user_id,
            )

        return await self._cache.get(
            key,
            load,
            force_refresh=force_refresh,
        )

    async def prewarm(self, *, user_id: str, company_id: str) -> bool:
        try:
            _ = await self.get_catalog(
                user_id=user_id,
                company_id=company_id,
                force_refresh=True,
            )
        except ConfigurationRequiredError:
            return False
        except Exception:
            logger.warning("Unable to prewarm the skill catalog", exc_info=True)
            return False
        return True


@final
class CurrentRequestCatalogAccessor:
    def __init__(self, service: SkillCatalogService) -> None:
        self._service = service

    async def get_catalog(
        self,
        *,
        force_refresh: bool = False,
    ) -> SkillCatalog:
        token = get_access_token()
        if token is None:
            raise ValueError("An authenticated access token is required")
        return await self._service.get_catalog(
            user_id=get_user_id(token),
            company_id=get_company_id(token),
            force_refresh=force_refresh,
        )


@lru_cache(maxsize=1)
def get_skill_catalog_service() -> SkillCatalogService:
    return SkillCatalogService(
        profile_repository=get_profile_repository(),
        credentials_repository=get_organization_credentials_repository(),
        cache=SkillCatalogCache(ttl_seconds=settings.skills_cache_ttl_seconds),
    )


@lru_cache(maxsize=1)
def get_catalog_accessor() -> CatalogAccessor:
    return CurrentRequestCatalogAccessor(get_skill_catalog_service())
