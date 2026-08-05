import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import final, override

import pytest
from key_value.aio.stores.memory import MemoryStore

from q_bridge_mcp.profiles.models import OrganizationCredentials, UserProfile
from q_bridge_mcp.profiles.repository import (
    OrganizationCredentialsRepository,
    UserProfileRepository,
)
from q_bridge_mcp.skills.catalog import (
    CatalogCacheKey,
    Skill,
    SkillCatalog,
    SkillCatalogCache,
    SkillFile,
    build_skill_catalog,
)
from q_bridge_mcp.skills.client import ContentNode, FolderNode
from q_bridge_mcp.skills.provider import UniqueSkillsProvider
from q_bridge_mcp.skills.service import SkillCatalogService
from q_bridge_mcp.tools.skills import get_skill_guide


@dataclass
class FakeKnowledgeBaseClient:
    folders: dict[str, list[FolderNode]]
    contents: dict[str, list[ContentNode]]
    payloads: dict[str, bytes]

    async def resolve_root_folder(self, folder_path: str) -> FolderNode:
        assert folder_path == "/skills-conduct"
        return FolderNode(id="root", name="skills-conduct", parent_id=None)

    async def list_folders(self, parent_id: str) -> list[FolderNode]:
        return self.folders.get(parent_id, [])

    async def list_contents(self, parent_id: str) -> list[ContentNode]:
        return self.contents.get(parent_id, [])

    async def download_content(self, content_id: str) -> bytes:
        return self.payloads[content_id]


@final
class ConcurrencyTrackingClient(FakeKnowledgeBaseClient):
    def __init__(
        self,
        folders: dict[str, list[FolderNode]],
        contents: dict[str, list[ContentNode]],
        payloads: dict[str, bytes],
    ) -> None:
        super().__init__(folders, contents, payloads)
        self.active_downloads: int = 0
        self.max_active_downloads: int = 0

    @override
    async def download_content(self, content_id: str) -> bytes:
        self.active_downloads += 1
        self.max_active_downloads = max(
            self.max_active_downloads,
            self.active_downloads,
        )
        await asyncio.sleep(0.01)
        self.active_downloads -= 1
        return self.payloads[content_id]


def skill_markdown(name: str, description: str) -> bytes:
    return (
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"
    ).encode()


def add_skill(
    *,
    folders: dict[str, list[FolderNode]],
    contents: dict[str, list[ContentNode]],
    payloads: dict[str, bytes],
    layer_id: str,
    layer_name: str,
    skill_id: str,
    skill_folder_name: str,
    skill_name: str,
    description: str,
) -> None:
    folders.setdefault("root", []).append(
        FolderNode(id=layer_id, name=layer_name, parent_id="root")
    )
    folders.setdefault(layer_id, []).append(
        FolderNode(id=skill_id, name=skill_folder_name, parent_id=layer_id)
    )
    content_id = f"{skill_id}-main"
    contents[skill_id] = [
        ContentNode(
            id=content_id,
            key="SKILL.md",
            mime_type="text/markdown",
            updated_at="2026-08-04T00:00:00Z",
        )
    ]
    payloads[content_id] = skill_markdown(skill_name, description)


@pytest.mark.ai
def test_build_skill_catalog__applies_unique_precedence_and_privacy() -> None:
    folders: dict[str, list[FolderNode]] = {}
    contents: dict[str, list[ContentNode]] = {}
    payloads: dict[str, bytes] = {}
    layers = [
        ("plain", "use-cases", "plain-skill", "Plain"),
        ("company-a", "company-a", "company-a-skill", "Company A"),
        ("company-z", "company-z", "company-z-skill", "Company Z"),
        ("space", "space-Research", "space-skill", "Space"),
        ("team-a", "team-alpha", "team-a-skill", "Team Alpha"),
        ("team-z", "team-zeta", "team-z-skill", "Team Zeta"),
        ("other-personal", "personal-other", "other-skill", "Other Personal"),
        ("own-personal", "personal-user-1", "own-skill", "Own Personal"),
    ]
    for layer_id, layer_name, skill_id, description in layers:
        add_skill(
            folders=folders,
            contents=contents,
            payloads=payloads,
            layer_id=layer_id,
            layer_name=layer_name,
            skill_id=skill_id,
            skill_folder_name=f"{skill_id}-folder",
            skill_name="shared-skill",
            description=description,
        )

    catalog = asyncio.run(
        build_skill_catalog(
            FakeKnowledgeBaseClient(folders, contents, payloads),
            root_folder="/skills-conduct",
            user_id="user-1",
        )
    )

    assert list(catalog.skills) == ["shared-skill"]
    assert catalog.skills["shared-skill"].description == "Own Personal"
    assert "space-skill-main" not in {
        skill_file.content_id
        for skill in catalog.skills.values()
        for skill_file in skill.files.values()
    }
    assert "other-skill-main" not in {
        skill_file.content_id
        for skill in catalog.skills.values()
        for skill_file in skill.files.values()
    }


@pytest.mark.ai
def test_build_skill_catalog__includes_nested_skill_subtree_and_manifest_hashes() -> None:
    folders = {
        "root": [FolderNode(id="group", name="use-cases", parent_id="root")],
        "group": [FolderNode(id="skill", name="report-writer", parent_id="group")],
        "skill": [FolderNode(id="refs", name="references", parent_id="skill")],
    }
    contents = {
        "skill": [
            ContentNode(
                id="main",
                key="skill.md",
                mime_type="text/markdown",
                updated_at="2026-08-04T00:00:00Z",
            )
        ],
        "refs": [
            ContentNode(
                id="reference",
                key="format.md",
                mime_type="text/markdown",
                updated_at="2026-08-04T00:00:00Z",
            )
        ],
    }
    payloads = {
        "main": skill_markdown("report-writer", "Writes reports"),
        "reference": b"# Required format",
    }

    catalog = asyncio.run(
        build_skill_catalog(
            FakeKnowledgeBaseClient(folders, contents, payloads),
            root_folder="skills-conduct",
            user_id="user-1",
        )
    )

    skill = catalog.skills["report-writer"]
    assert list(skill.files) == ["SKILL.md", "references/format.md"]
    assert skill.files["references/format.md"].content == b"# Required format"
    assert skill.files["references/format.md"].hash.startswith("sha256:")


@pytest.mark.ai
def test_build_skill_catalog__skips_names_that_cannot_form_skill_uris() -> None:
    folders = {
        "root": [FolderNode(id="skill", name="invalid", parent_id="root")],
    }
    contents = {
        "skill": [
            ContentNode(
                id="main",
                key="SKILL.md",
                mime_type="text/markdown",
                updated_at=None,
            )
        ]
    }
    payloads = {
        "main": skill_markdown("Invalid Skill", "Invalid URI name"),
    }

    catalog = asyncio.run(
        build_skill_catalog(
            FakeKnowledgeBaseClient(folders, contents, payloads),
            root_folder="skills-conduct",
            user_id="user-1",
        )
    )

    assert catalog.skills == {}


@pytest.mark.ai
def test_build_skill_catalog__downloads_skill_files_concurrently() -> None:
    client = ConcurrencyTrackingClient(
        folders={
            "root": [FolderNode(id="skill", name="writer", parent_id="root")],
        },
        contents={
            "skill": [
                ContentNode(
                    id="main",
                    key="SKILL.md",
                    mime_type="text/markdown",
                    updated_at=None,
                ),
                ContentNode(
                    id="reference",
                    key="reference.md",
                    mime_type="text/markdown",
                    updated_at=None,
                ),
            ]
        },
        payloads={
            "main": skill_markdown("writer", "Writes content"),
            "reference": b"# Reference",
        },
    )

    _ = asyncio.run(
        build_skill_catalog(
            client,
            root_folder="skills-conduct",
            user_id="user-1",
        )
    )

    assert client.max_active_downloads == 2


@pytest.mark.ai
def test_skill_catalog_cache__reuses_entries_until_forced_or_expired() -> None:
    now = 100.0
    loads = 0
    catalog = SkillCatalog(skills={})
    key = CatalogCacheKey(
        company_id="company-1",
        user_id="user-1",
        root_folder="skills-conduct",
        credentials_version="2026-08-04T00:00:00+00:00",
    )

    async def load() -> SkillCatalog:
        nonlocal loads
        loads += 1
        return catalog

    cache = SkillCatalogCache(ttl_seconds=60, clock=lambda: now)

    assert asyncio.run(cache.get(key, load)) is catalog
    assert asyncio.run(cache.get(key, load)) is catalog
    assert loads == 1

    assert asyncio.run(cache.get(key, load, force_refresh=True)) is catalog
    assert loads == 2

    now = 161.0
    assert asyncio.run(cache.get(key, load)) is catalog
    assert loads == 3


@pytest.mark.ai
def test_skill_catalog_service__prewarms_the_catalog_cache() -> None:
    storage = MemoryStore()
    profile_repository = UserProfileRepository(storage)
    credentials_repository = OrganizationCredentialsRepository(storage)
    client = FakeKnowledgeBaseClient(
        folders={
            "root": [FolderNode(id="skill", name="writer", parent_id="root")],
        },
        contents={
            "skill": [
                ContentNode(
                    id="main",
                    key="SKILL.md",
                    mime_type="text/markdown",
                    updated_at=None,
                )
            ]
        },
        payloads={"main": skill_markdown("writer", "Writes content")},
    )
    client_creations = 0

    def create_client(
        user_id: str,
        company_id: str,
        credentials: OrganizationCredentials,
    ) -> FakeKnowledgeBaseClient:
        nonlocal client_creations
        del user_id, company_id, credentials
        client_creations += 1
        return client

    service = SkillCatalogService(
        profile_repository=profile_repository,
        credentials_repository=credentials_repository,
        cache=SkillCatalogCache(ttl_seconds=60),
        client_factory=create_client,
    )

    async def run_scenario() -> None:
        await profile_repository.save(
            company_id="company-1",
            user_id="user-1",
            profile=UserProfile(skillsRootFolder="skills-conduct"),
        )
        await credentials_repository.save(
            company_id="company-1",
            credentials=OrganizationCredentials(
                appId="app-1",
                apiKey="secret",
                configuredBy="user-1",
                updatedAt=datetime(2026, 8, 4, tzinfo=UTC),
            ),
        )

        assert await service.prewarm(user_id="user-1", company_id="company-1")
        catalog = await service.get_catalog(
            user_id="user-1",
            company_id="company-1",
        )
        assert list(catalog.skills) == ["writer"]

    asyncio.run(run_scenario())

    assert client_creations == 1


@final
class FakeCatalogAccessor:
    def __init__(self, catalog: SkillCatalog) -> None:
        self.catalog = catalog
        self.force_refresh_values: list[bool] = []

    async def get_catalog(self, *, force_refresh: bool = False) -> SkillCatalog:
        self.force_refresh_values.append(force_refresh)
        return self.catalog


@final
class RequestOnlyCatalogAccessor:
    async def get_catalog(self, *, force_refresh: bool = False) -> SkillCatalog:
        del force_refresh
        raise RuntimeError("No authenticated request")


def make_catalog() -> SkillCatalog:
    main_content = skill_markdown("report-writer", "Writes reports")
    return SkillCatalog(
        skills={
            "report-writer": Skill(
                name="report-writer",
                description="Writes reports",
                source_path="company-core/report-writer",
                files={
                    "SKILL.md": SkillFile(
                        path="SKILL.md",
                        content_id="main",
                        mime_type="text/markdown",
                        content=main_content,
                        updated_at="2026-08-04T00:00:00Z",
                    ),
                    "references/format.md": SkillFile(
                        path="references/format.md",
                        content_id="reference",
                        mime_type="text/markdown",
                        content=b"# Required format",
                        updated_at="2026-08-04T00:00:00Z",
                    ),
                },
            )
        }
    )


@pytest.mark.ai
def test_unique_skills_provider__exposes_main_manifest_and_supporting_resources() -> None:
    accessor = FakeCatalogAccessor(make_catalog())
    provider = UniqueSkillsProvider(accessor)

    resources = asyncio.run(provider.list_resources())

    assert [str(resource.uri) for resource in resources] == [
        "skill://report-writer/SKILL.md",
        "skill://report-writer/_manifest",
        "skill://report-writer/references/format.md",
    ]
    manifest_resource = resources[1]
    manifest = asyncio.run(manifest_resource.read())
    assert isinstance(manifest, str)
    assert '"path": "references/format.md"' in manifest
    assert '"hash": "sha256:' in manifest


@pytest.mark.ai
def test_unique_skills_provider__skips_request_resources_during_task_discovery() -> None:
    provider = UniqueSkillsProvider(RequestOnlyCatalogAccessor())

    assert asyncio.run(provider.get_tasks()) == []


@pytest.mark.ai
def test_remote_skill_resource__revalidates_catalog_when_read() -> None:
    accessor = FakeCatalogAccessor(make_catalog())
    provider = UniqueSkillsProvider(accessor)
    resource = asyncio.run(
        provider.get_resource("skill://report-writer/references/format.md")
    )

    assert resource is not None
    assert asyncio.run(resource.read()) == "# Required format"
    assert accessor.force_refresh_values == [False, False]


@pytest.mark.ai
def test_get_skill_guide__forces_refresh_and_supports_progressive_disclosure() -> None:
    accessor = FakeCatalogAccessor(make_catalog())

    listing = asyncio.run(get_skill_guide(None, None, True, accessor))
    files = asyncio.run(get_skill_guide("report-writer", None, False, accessor))
    content = asyncio.run(
        get_skill_guide(
            "report-writer",
            "references/format.md",
            False,
            accessor,
        )
    )

    assert listing["skills"] == [
        {
            "name": "report-writer",
            "description": "Writes reports",
            "uri": "skill://report-writer/SKILL.md",
        }
    ]
    assert files["files"][0]["path"] == "SKILL.md"
    assert content["content"] == "# Required format"
    assert content["encoding"] == "utf-8"
    assert "Read the SKILL.md" in listing["requiredNextStep"]
    assert accessor.force_refresh_values == [True, False, False]
