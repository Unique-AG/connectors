"""Ticket 6, counted rather than timed: a second filter must not re-walk.

Drives the real ``content_tree`` against the real ``ContentTree`` with only
``unique_sdk`` faked, so it counts requests the backend would have served.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import unique_sdk
from pydantic import SecretStr

from kb_mcp.tools.content_tree import ContentTreeToolConfig, content_tree
from kb_mcp.tools.content_tree import cache as ct_cache

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
_PDF_ONLY = {"operator": "equals", "path": ["mimeType"], "value": "application/pdf"}
_TEXT_ONLY = {"operator": "equals", "path": ["mimeType"], "value": "text/plain"}

_FOLDERS: dict[str | None, list[dict[str, Any]]] = {
    None: [
        {"id": "scope_docs", "name": "Docs", "parentId": None},
        {"id": "scope_arch", "name": "Archive", "parentId": None},
    ],
    "scope_docs": [{"id": "scope_sub", "name": "Sub", "parentId": "scope_docs"}],
    "scope_arch": [],
    "scope_sub": [],
}


def _content(cid: str, key: str, mime: str, folder: str) -> dict[str, Any]:
    return {
        "id": cid,
        "object": "content",
        "key": key,
        "byteSize": 1,
        "mimeType": mime,
        "ownerId": folder,
        "createdAt": NOW,
        "updatedAt": NOW,
        "metadata": {"folderIdPath": f"uniquepathid://{folder}"},
    }


_CONTENTS: dict[str, list[dict[str, Any]]] = {
    "scope_docs": [
        _content("c_pdf", "report.pdf", "application/pdf", "scope_docs"),
        _content("c_txt", "notes.txt", "text/plain", "scope_docs"),
    ],
    "scope_arch": [_content("c_old", "old.pdf", "application/pdf", "scope_arch")],
    "scope_sub": [_content("c_deep", "deep.pdf", "application/pdf", "scope_sub")],
}


@pytest.fixture
def requests(monkeypatch) -> Counter[str]:
    """Counts every listing the knowledge base would have served."""
    seen: Counter[str] = Counter()

    async def _folders(*, parentId=None, skip=0, take=100, **_: Any) -> dict[str, Any]:
        seen["folder"] += 1
        items = _FOLDERS.get(parentId, [])
        return {"folderInfos": items[skip : skip + take], "totalCount": len(items)}

    async def _contents(*, parentId=None, skip=0, take=100, **_: Any) -> dict[str, Any]:
        seen["content"] += 1
        items = _CONTENTS.get(parentId, [])
        return {"contentInfos": items[skip : skip + take], "totalCount": len(items)}

    async def _scope_id(*, folder_path: str, **_: Any) -> str:
        return {"/Docs": "scope_docs", "/Archive": "scope_arch"}[folder_path]

    # Patched on unique_sdk itself, so both the scoped walk and unique_toolkit's
    # own unscoped walk are covered wherever they reach for the SDK.
    monkeypatch.setattr(unique_sdk.Folder, "get_infos_async", _folders)
    monkeypatch.setattr(unique_sdk.Content, "get_infos_async", _contents)
    monkeypatch.setattr(
        unique_sdk.Folder, "resolve_scope_id_from_folder_path_async", _scope_id
    )
    ct_cache._tree_cache = None
    yield seen
    ct_cache._tree_cache = None


@pytest.fixture(autouse=True)
def _identity(monkeypatch):
    settings = MagicMock()
    settings.authcontext.get_confidential_company_id.return_value = "company-1"
    settings.authcontext.get_confidential_user_id.return_value = "user-1"
    settings.authcontext.company_id = SecretStr("company-1")
    settings.authcontext.user_id = SecretStr("user-1")
    monkeypatch.setattr(
        "kb_mcp.tools.content_tree.tool.get_unique_settings_async",
        AsyncMock(return_value=settings),
    )


async def _list(metadata_filter: dict[str, Any] | None, folder_path: str) -> str:
    result = await content_tree(
        mode="list",
        folder_path=folder_path,
        metadata_filter=metadata_filter,
        config=ContentTreeToolConfig(),
    )
    assert result.is_error is not True, result.content[0].text  # type: ignore[union-attr]
    return result.content[0].text  # type: ignore[union-attr]


async def test_a_second_filter_is_served_without_another_walk(requests):
    """Ticket 6: distinct filters share one walk, and still filter differently."""
    pdf = await _list(_PDF_ONLY, "Docs")
    after_first = requests.total()

    txt = await _list(_TEXT_ONLY, "Docs")

    assert requests.total() == after_first, "a second filter re-walked the folder"
    assert "report.pdf" in pdf and "notes.txt" not in pdf
    assert "notes.txt" in txt and "report.pdf" not in txt


async def test_a_second_folder_does_walk_again(requests):
    """Control: the counter really does detect a walk, so the test above means
    something. A new scope is a new cache entry and must cost new requests."""
    await _list(_PDF_ONLY, "Docs")
    after_first = requests.total()

    await _list(_PDF_ONLY, "Archive")

    assert requests.total() > after_first
