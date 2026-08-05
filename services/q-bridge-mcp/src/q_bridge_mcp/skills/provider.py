from __future__ import annotations

import json
import mimetypes
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Any, cast, final, override
from urllib.parse import quote, unquote, urlsplit

from fastmcp.resources.base import Resource, ResourceResult
from fastmcp.server.providers.base import Provider
from fastmcp.utilities.components import FastMCPComponent
from fastmcp.utilities.versions import VersionSpec
from pydantic import AnyUrl

from q_bridge_mcp.skills.catalog import MAIN_FILE_NAME, Skill
from q_bridge_mcp.skills.service import CatalogAccessor, get_catalog_accessor


class RemoteSkillResource(Resource):
    skill_name: str
    file_path: str
    is_manifest: bool = False
    accessor: object

    @override
    def get_meta(self) -> dict[str, Any]:
        meta = super().get_meta()
        fastmcp_meta = cast(dict[str, Any], meta["fastmcp"])
        fastmcp_meta["skill"] = {
            "name": self.skill_name,
            "is_manifest": self.is_manifest,
        }
        return meta

    @override
    async def read(self) -> str | bytes | ResourceResult:
        catalog = await cast(CatalogAccessor, self.accessor).get_catalog()
        skill = catalog.skills.get(self.skill_name)
        if skill is None:
            raise FileNotFoundError(f"Unknown skill: {self.skill_name}")
        if self.is_manifest:
            return _manifest(skill)
        skill_file = skill.files.get(self.file_path)
        if skill_file is None:
            raise FileNotFoundError(
                f"Unknown file {self.file_path!r} in skill {self.skill_name!r}"
            )
        if skill_file.mime_type.startswith("text/"):
            return skill_file.content.decode("utf-8")
        return skill_file.content


@final
class UniqueSkillsProvider(Provider):
    def __init__(self, accessor: CatalogAccessor | None = None) -> None:
        super().__init__()
        self._accessor = accessor or get_catalog_accessor()

    @override
    async def get_tasks(self) -> Sequence[FastMCPComponent]:
        return []

    @override
    async def _list_resources(self) -> Sequence[Resource]:
        catalog = await self._accessor.get_catalog()
        resources = [
            resource
            for skill in catalog.skills.values()
            for resource in _resources_for_skill(skill, self._accessor)
        ]
        return resources

    @override
    async def _get_resource(
        self,
        uri: str,
        version: VersionSpec | None = None,
    ) -> Resource | None:
        del version
        parsed = _parse_skill_uri(uri)
        if parsed is None:
            return None
        skill_name, file_path = parsed
        catalog = await self._accessor.get_catalog()
        skill = catalog.skills.get(skill_name)
        if skill is None:
            return None
        if file_path == "_manifest":
            return _resource_for_manifest(skill, self._accessor)
        if file_path not in skill.files:
            return None
        return _resource_for_file(skill, file_path, self._accessor)


def _resources_for_skill(
    skill: Skill,
    accessor: CatalogAccessor,
) -> list[Resource]:
    resources: list[Resource] = [
        _resource_for_file(skill, MAIN_FILE_NAME, accessor),
        _resource_for_manifest(skill, accessor),
    ]
    resources.extend(
        _resource_for_file(skill, file_path, accessor)
        for file_path in skill.files
        if file_path != MAIN_FILE_NAME
    )
    return resources


def _resource_for_manifest(
    skill: Skill,
    accessor: CatalogAccessor,
) -> RemoteSkillResource:
    return RemoteSkillResource(
        uri=AnyUrl(f"skill://{skill.name}/_manifest"),
        name=f"{skill.name}/_manifest",
        description=f"File listing for {skill.name}",
        mime_type="application/json",
        skill_name=skill.name,
        file_path="_manifest",
        is_manifest=True,
        accessor=accessor,
    )


def _resource_for_file(
    skill: Skill,
    file_path: str,
    accessor: CatalogAccessor,
) -> RemoteSkillResource:
    mime_type, _ = mimetypes.guess_type(file_path)
    return RemoteSkillResource(
        uri=AnyUrl(f"skill://{skill.name}/{quote(file_path, safe='/')}"),
        name=f"{skill.name}/{file_path}",
        description=(
            skill.description
            if file_path == MAIN_FILE_NAME
            else f"File from {skill.name} skill"
        ),
        mime_type=mime_type or skill.files[file_path].mime_type,
        skill_name=skill.name,
        file_path=file_path,
        accessor=accessor,
    )


def _manifest(skill: Skill) -> str:
    return json.dumps(
        {
            "skill": skill.name,
            "files": [
                {
                    "path": skill_file.path,
                    "size": skill_file.size,
                    "hash": skill_file.hash,
                }
                for skill_file in skill.files.values()
            ],
        },
        indent=2,
    )


def _parse_skill_uri(uri: str) -> tuple[str, str] | None:
    parsed = urlsplit(uri)
    if parsed.scheme != "skill" or not parsed.netloc:
        return None
    file_path = unquote(parsed.path.lstrip("/"))
    path = PurePosixPath(file_path)
    if (
        not file_path
        or "\x00" in file_path
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        return None
    return parsed.netloc, file_path


skills_provider = UniqueSkillsProvider()
