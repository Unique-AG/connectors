from __future__ import annotations

import asyncio
import hashlib
import re
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import final

from fastmcp.server.providers.skills._common import parse_frontmatter

from q_bridge_mcp.skills.client import ContentNode, FolderNode, KnowledgeBaseClient

MAIN_FILE_NAME = "SKILL.md"
MAX_CACHE_ENTRIES = 256
MAX_CONCURRENT_UNIQUE_REQUESTS = 8
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_NAME_MAX_LENGTH = 64


@dataclass(frozen=True)
class SkillFile:
    path: str
    content_id: str
    mime_type: str
    content: bytes
    updated_at: str | None

    @property
    def size(self) -> int:
        return len(self.content)

    @property
    def hash(self) -> str:
        return f"sha256:{hashlib.sha256(self.content).hexdigest()}"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    source_path: str
    files: Mapping[str, SkillFile]


@dataclass(frozen=True)
class SkillCatalog:
    skills: Mapping[str, Skill]


@dataclass(frozen=True)
class CatalogCacheKey:
    company_id: str
    user_id: str
    root_folder: str
    credentials_version: str


@dataclass(frozen=True)
class _CacheEntry:
    catalog: SkillCatalog
    expires_at: float


@dataclass(frozen=True)
class _FolderState:
    folder: FolderNode
    path: tuple[str, ...]


@dataclass(frozen=True)
class _SkillCandidate:
    skill: Skill
    precedence: tuple[int, str, str]


@dataclass(frozen=True)
class _FolderListing:
    contents: list[ContentNode]
    folders: list[FolderNode]


@dataclass(frozen=True)
class _SkillFileListing:
    state: _FolderState
    files: Mapping[str, ContentNode]


@final
class SkillCatalogCache:
    def __init__(
        self,
        *,
        ttl_seconds: int,
        max_entries: int = MAX_CACHE_ENTRIES,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[CatalogCacheKey, _CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(
        self,
        key: CatalogCacheKey,
        loader: Callable[[], Awaitable[SkillCatalog]],
        *,
        force_refresh: bool = False,
    ) -> SkillCatalog:
        async with self._lock:
            now = self._clock()
            entry = self._entries.get(key)
            if not force_refresh and entry is not None and entry.expires_at > now:
                self._entries.move_to_end(key)
                return entry.catalog

            catalog = await loader()
            self._entries[key] = _CacheEntry(
                catalog=catalog,
                expires_at=now + self._ttl_seconds,
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                _ = self._entries.popitem(last=False)
            return catalog


async def build_skill_catalog(
    client: KnowledgeBaseClient,
    *,
    root_folder: str,
    user_id: str,
) -> SkillCatalog:
    root = await client.resolve_root_folder(f"/{root_folder.strip('/')}")
    states: dict[str, _FolderState] = {
        root.id: _FolderState(folder=root, path=()),
    }
    children: dict[str, list[str]] = {}
    contents: dict[str, list[ContentNode]] = {}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_UNIQUE_REQUESTS)

    async def inspect_folder(folder_id: str) -> _FolderListing:
        async def list_contents() -> list[ContentNode]:
            async with semaphore:
                return await client.list_contents(folder_id)

        async def list_folders() -> list[FolderNode]:
            async with semaphore:
                return await client.list_folders(folder_id)

        folder_contents, folders = await asyncio.gather(
            list_contents(),
            list_folders(),
        )
        return _FolderListing(contents=folder_contents, folders=folders)

    frontier = [root.id]
    while frontier:
        listings = await asyncio.gather(
            *(inspect_folder(folder_id) for folder_id in frontier)
        )
        next_frontier: list[str] = []
        for folder_id, listing in zip(frontier, listings, strict=True):
            state = states[folder_id]
            contents[folder_id] = listing.contents
            child_ids: list[str] = []
            for child in listing.folders:
                child_path = (*state.path, child.name)
                if len(child_path) == 1 and not _include_root_layer(
                    child.name,
                    user_id=user_id,
                ):
                    continue
                if child.id in states:
                    continue
                states[child.id] = _FolderState(folder=child, path=child_path)
                child_ids.append(child.id)
                next_frontier.append(child.id)
            children[folder_id] = child_ids
        frontier = next_frontier

    skill_file_listings: list[_SkillFileListing] = []
    for folder_id, state in states.items():
        main_content = next(
            (
                content
                for content in contents.get(folder_id, [])
                if content.key.casefold() == MAIN_FILE_NAME.casefold()
            ),
            None,
        )
        if main_content is None:
            continue

        files: dict[str, ContentNode] = {}
        descendant_queue: deque[tuple[str, tuple[str, ...]]] = deque(
            [(folder_id, ())]
        )
        while descendant_queue:
            descendant_id, relative_folder = descendant_queue.popleft()
            for content in contents.get(descendant_id, []):
                relative_path = (
                    MAIN_FILE_NAME
                    if descendant_id == folder_id and content.id == main_content.id
                    else "/".join((*relative_folder, content.key))
                )
                files[relative_path] = content
            for child_id in children.get(descendant_id, []):
                child_name = states[child_id].folder.name
                descendant_queue.append((child_id, (*relative_folder, child_name)))

        skill_file_listings.append(_SkillFileListing(state=state, files=files))

    content_by_id = {
        content.id: content
        for listing in skill_file_listings
        for content in listing.files.values()
    }

    async def download_content(content: ContentNode) -> bytes:
        async with semaphore:
            return await client.download_content(content.id)

    content_ids = list(content_by_id)
    payloads = await asyncio.gather(
        *(download_content(content_by_id[content_id]) for content_id in content_ids)
    )
    payload_by_id = dict(zip(content_ids, payloads, strict=True))

    candidates: list[_SkillCandidate] = []
    for listing in skill_file_listings:
        skill_files = {
            path: SkillFile(
                path=path,
                content_id=content.id,
                mime_type=content.mime_type,
                content=payload_by_id[content.id],
                updated_at=content.updated_at,
            )
            for path, content in listing.files.items()
        }
        main_file = skill_files.get(MAIN_FILE_NAME)
        if main_file is None:
            continue
        try:
            main_text = main_file.content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        frontmatter, _ = parse_frontmatter(main_text)
        name = frontmatter.get("name")
        description = frontmatter.get("description")
        if not isinstance(name, str) or not name.strip():
            continue
        normalized_name = name.strip()
        if (
            len(normalized_name) > SKILL_NAME_MAX_LENGTH
            or SKILL_NAME_PATTERN.fullmatch(normalized_name) is None
        ):
            continue
        if not isinstance(description, str) or not description.strip():
            continue

        source_path = "/".join(listing.state.path)
        candidates.append(
            _SkillCandidate(
                skill=Skill(
                    name=normalized_name,
                    description=description.strip(),
                    source_path=source_path,
                    files=dict(sorted(skill_files.items())),
                ),
                precedence=_precedence(listing.state.path),
            )
        )

    selected: dict[str, _SkillCandidate] = {}
    for candidate in candidates:
        current = selected.get(candidate.skill.name)
        if current is None or candidate.precedence > current.precedence:
            selected[candidate.skill.name] = candidate

    return SkillCatalog(
        skills={
            name: candidate.skill
            for name, candidate in sorted(selected.items())
        }
    )


def _include_root_layer(name: str, *, user_id: str) -> bool:
    if name.startswith("space-"):
        return False
    if name.startswith("personal-"):
        return name == f"personal-{user_id}"
    return True


def _precedence(path: tuple[str, ...]) -> tuple[int, str, str]:
    layer_name = path[0] if path else ""
    if layer_name.startswith("personal-"):
        rank = 4
    elif layer_name.startswith("team-"):
        rank = 3
    elif layer_name.startswith("company-"):
        rank = 2
    else:
        rank = 1
    return rank, layer_name, "/".join(path)
