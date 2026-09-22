"""Tests for the packaged agent skills: discovery, frontmatter, resource URIs."""

import json
from pathlib import Path

import pytest
from fastmcp.server.providers.skills import SkillProvider, SkillsDirectoryProvider

import kb_mcp

pytestmark = pytest.mark.ai

SKILLS_ROOT = Path(kb_mcp.__file__).parent / "skills"
MARKETPLACE = (
    Path(__file__).resolve().parents[3] / ".claude-plugin" / "marketplace.json"
)
# Tolerate a missing root so a dropped skills directory fails the assertion
# below rather than erroring during collection.
SKILL_DIRS = sorted(p for p in SKILLS_ROOT.glob("*") if p.is_dir())


def test_package_directory_contains_at_least_one_skill():
    """Only src/ reaches the wheel, so a skill outside the package is absent at runtime."""
    assert SKILL_DIRS


@pytest.mark.skipif(not MARKETPLACE.exists(), reason="needs a repo checkout")
def test_marketplace_manifest_covers_the_packaged_skills():
    """npx discovery reads only this manifest, so a stale source finds nothing, silently."""
    plugins = json.loads(MARKETPLACE.read_text())["plugins"]
    declared = {
        (MARKETPLACE.parents[1] / p["source"] / "skills").resolve() for p in plugins
    }
    assert SKILLS_ROOT.resolve() in declared
    for path in declared:
        assert path.is_dir(), path


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_directory_name_matches_frontmatter_name(skill_dir: Path):
    """The server names a skill after its directory, the npx CLI reads frontmatter."""
    frontmatter = SkillProvider(skill_dir).skill_info.frontmatter
    assert frontmatter.get("name") == skill_dir.name
    assert frontmatter.get("description")


async def test_every_skill_is_listed_as_a_resource():
    uris = {
        str(r.uri) for r in await SkillsDirectoryProvider(SKILLS_ROOT).list_resources()
    }
    expected = {f"skill://{d.name}/SKILL.md" for d in SKILL_DIRS}
    assert expected <= uris


async def test_unique_kb_mcp_body_is_readable():
    resource = await SkillsDirectoryProvider(SKILLS_ROOT).get_resource(
        "skill://unique-kb-mcp/SKILL.md"
    )
    assert resource is not None
    assert "content_tree" in await resource.read()
