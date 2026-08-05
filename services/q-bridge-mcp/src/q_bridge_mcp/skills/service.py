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
            logger.info(
                "Skill catalog unavailable because Q Bridge setup is incomplete (user_id=%s, company_id=%s)",
                user_id,
                company_id,
            )
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
            logger.info(
                "Loading skill catalog from the Unique Knowledge Base (force_refresh=%s, user_id=%s, company_id=%s)",
                force_refresh,
                user_id,
                company_id,
            )
            client = self._client_factory(user_id, company_id, credentials)
            catalog = await build_skill_catalog(
                client,
                root_folder=root_folder,
                user_id=user_id,
            )
            logger.info(
                "Loaded skill catalog from the Unique Knowledge Base (skill_count=%d, user_id=%s, company_id=%s)",
                len(catalog.skills),
                user_id,
                company_id,
            )
            return catalog

        catalog = await self._cache.get(
            key,
            load,
            force_refresh=force_refresh,
        )
        logger.info(
            "Served skill catalog (skill_count=%d, user_id=%s, company_id=%s)",
            len(catalog.skills),
            user_id,
            company_id,
        )
        return catalog

    async def prewarm(self, *, user_id: str, company_id: str) -> bool:
        try:
            catalog = await self.get_catalog(
                user_id=user_id,
                company_id=company_id,
                force_refresh=True,
            )
        except ConfigurationRequiredError:
            logger.info(
                "Skipped skill catalog prewarm because setup is incomplete (user_id=%s, company_id=%s)",
                user_id,
                company_id,
            )
            return False
        except Exception as error:  # noqa: BLE001  # prewarm must not block profile saves
            logger.warning(
                "Unable to prewarm the skill catalog (error_type=%s, user_id=%s, company_id=%s)",
                type(error).__name__,
                user_id,
                company_id,
            )
            return False
        logger.info(
            "Prewarmed skill catalog from the Unique Knowledge Base (skill_count=%d, user_id=%s, company_id=%s)",
            len(catalog.skills),
            user_id,
            company_id,
        )
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
