"""Tests for resolve_scope_ids — concurrency bound and partial-failure handling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from unique_toolkit.content.schemas import Content, ContentChunk, ContentMetadata

from kb_mcp.tools.search.scope_resolver import resolve_scope_ids

pytestmark = pytest.mark.ai


def _metadata(folder_id_path: str) -> ContentMetadata:
    return ContentMetadata(key="k", mimeType="text/plain", folderIdPath=folder_id_path)


def _chunk(content_id: str, folder_id_path: str | None = None) -> ContentChunk:
    metadata = _metadata(folder_id_path) if folder_id_path else None
    return ContentChunk(id=content_id, text="x", order=0, metadata=metadata)


def _content(content_id: str, folder_id_path: str | None) -> Content:
    metadata = {"folderIdPath": folder_id_path} if folder_id_path else None
    return Content(id=content_id, key=content_id, title=content_id, metadata=metadata)


def _make_settings(company_id: str = "company-1", user_id: str = "user-1"):
    settings = MagicMock()
    settings.authcontext.get_confidential_company_id.return_value = company_id
    settings.authcontext.get_confidential_user_id.return_value = user_id
    return settings


@pytest.mark.asyncio
async def test_chunks_with_existing_metadata_skip_the_network_lookup():
    chunks = [_chunk("c1", "uniquepathid://root/scope_1")]
    with patch(
        "kb_mcp.tools.search.scope_resolver.search_contents_async",
        new=AsyncMock(),
    ) as mock_search:
        resolved = await resolve_scope_ids(
            chunks, _make_settings(), lookup_concurrency=4
        )

    mock_search.assert_not_called()
    assert resolved == {"c1": "scope_1"}


@pytest.mark.asyncio
async def test_mixed_success_and_failure_resolves_the_successful_ones():
    chunks = [_chunk("c1"), _chunk("c2"), _chunk("c3")]

    async def fake_search(*, where, **_kwargs):
        content_id = where["id"]["equals"]
        if content_id == "c1":
            return [_content("c1", "uniquepathid://root/scope_1")]
        if content_id == "c2":
            raise RuntimeError("boom")
        return []  # c3: not found

    with patch(
        "kb_mcp.tools.search.scope_resolver.search_contents_async",
        new=AsyncMock(side_effect=fake_search),
    ):
        resolved = await resolve_scope_ids(
            chunks, _make_settings(), lookup_concurrency=4
        )

    assert resolved == {"c1": "scope_1"}


@pytest.mark.asyncio
async def test_chunks_sharing_a_content_id_are_looked_up_once():
    """Several chunks per document is the normal search-result shape."""
    chunks = [_chunk("c1"), _chunk("c1"), _chunk("c1")]

    with patch(
        "kb_mcp.tools.search.scope_resolver.search_contents_async",
        new=AsyncMock(return_value=[_content("c1", "uniquepathid://root/scope_1")]),
    ) as mock_search:
        resolved = await resolve_scope_ids(
            chunks, _make_settings(), lookup_concurrency=4
        )

    assert mock_search.await_count == 1
    assert resolved == {"c1": "scope_1"}


@pytest.mark.asyncio
async def test_lookup_uses_the_callers_identity():
    seen: dict[str, str] = {}

    async def capture_identity(*, user_id, company_id, **_kwargs):
        seen["user_id"] = user_id
        seen["company_id"] = company_id
        return []

    with patch(
        "kb_mcp.tools.search.scope_resolver.search_contents_async",
        new=AsyncMock(side_effect=capture_identity),
    ):
        await resolve_scope_ids(
            [_chunk("c1")],
            _make_settings(company_id="company-9", user_id="user-9"),
            lookup_concurrency=4,
        )

    assert seen == {"user_id": "user-9", "company_id": "company-9"}


@pytest.mark.asyncio
async def test_all_lookups_failing_returns_empty_without_raising():
    chunks = [_chunk("c1"), _chunk("c2")]

    async def always_fails(**_kwargs):
        raise RuntimeError("boom")

    with patch(
        "kb_mcp.tools.search.scope_resolver.search_contents_async",
        new=AsyncMock(side_effect=always_fails),
    ):
        resolved = await resolve_scope_ids(
            chunks, _make_settings(), lookup_concurrency=4
        )

    assert resolved == {}


@pytest.mark.asyncio
async def test_concurrent_lookups_never_exceed_lookup_concurrency():
    chunks = [_chunk(f"c{i}") for i in range(10)]
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def tracked_search(*, where, **_kwargs):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        async with lock:
            in_flight -= 1
        return []

    with patch(
        "kb_mcp.tools.search.scope_resolver.search_contents_async",
        new=AsyncMock(side_effect=tracked_search),
    ):
        await resolve_scope_ids(chunks, _make_settings(), lookup_concurrency=3)

    # == not <=: 10 lookups against a limit of 3 must saturate the semaphore,
    # so a regression that serialized them would still satisfy <=.
    assert max_in_flight == 3
