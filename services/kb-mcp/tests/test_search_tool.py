"""Tests for the search tool — config schema, routing logic, and references."""

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.tools import ToolResult
from unique_mcp.meta.rjsf import ConfigSchemaMeta
from unique_toolkit.content.schemas import ContentChunk, ContentMetadata
from unique_toolkit.experimental.components.internal_search import (
    KnowledgeBaseInternalSearchConfig,
)

from kb_mcp.references import (
    GENERIC_RESULT_CITATION_INSTRUCTION,
    REFERENCE_META_KEY,
    SEARCH_SYSTEM_PROMPT,
    TOOL_DESCRIPTION_CITATION_GUIDANCE,
    UNIQUE_AI_RESULT_CITATION_INSTRUCTION,
    UNIQUE_AI_TOOL_FORMAT_INFORMATION,
    chunk_to_text_content,
    frontend_document_url,
    is_unique_ai_client,
    markdown_citation_link,
    reference_url,
    scope_id_from_folder_id_path,
)
from kb_mcp.tools.search import SearchToolConfig, search


def test_json_schema_has_service_config():
    schema = SearchToolConfig.model_json_schema()
    assert "serviceConfig" in schema["properties"]


def test_json_schema_service_config_has_metadata_filter():
    schema = SearchToolConfig.model_json_schema()
    sc_ref = schema["properties"]["serviceConfig"].get("$ref", "")
    def_name = sc_ref.split("/")[-1]
    kb_props = schema["$defs"][def_name]["properties"]
    assert "metadataFilter" in kb_props


def test_ui_schema_hides_max_tokens_for_sources():
    meta: dict = {}
    ConfigSchemaMeta(SearchToolConfig).merge_into_meta(meta)
    ui = meta["unique.app/config-schema"]["ui_schema"]
    assert ui["postProcessing"]["maxTokensForSources"] == {"ui:widget": "hidden"}


def test_default_config_round_trips():
    default = SearchToolConfig().model_dump(mode="json")
    restored = SearchToolConfig.model_validate(default)
    assert isinstance(restored.service_config, KnowledgeBaseInternalSearchConfig)


def test_tool_description_includes_citation_rules():
    description = search.__fastmcp__.description
    assert description is not None
    assert "Do NOT invent placeholders like [source1]" in description
    assert TOOL_DESCRIPTION_CITATION_GUIDANCE in description


def test_tool_meta_uses_unique_ai_format_and_slim_system_prompt():
    meta = search.__fastmcp__.meta or {}
    assert (
        meta["unique.app/tool-format-information"] == UNIQUE_AI_TOOL_FORMAT_INFORMATION
    )
    assert "[source" in meta["unique.app/tool-format-information"]
    assert (
        "Do NOT invent placeholders" not in meta["unique.app/tool-format-information"]
    )
    assert meta["unique.app/system-prompt"] == SEARCH_SYSTEM_PROMPT
    assert TOOL_DESCRIPTION_CITATION_GUIDANCE not in meta["unique.app/system-prompt"]


def _make_chunk(text: str, **kwargs) -> ContentChunk:
    return ContentChunk(
        id=kwargs.pop("id", "cont_abcdefgehijklmnopqrstuvwx"),
        text=text,
        order=0,
        **kwargs,
    )


def _patch_post_processor(chunks: list):
    """Patch InternalSearchPostProcessor so process() returns the given chunks."""
    mock_pp = MagicMock()
    mock_pp.process = AsyncMock(return_value=chunks)
    return patch(
        "kb_mcp.tools.search.tool.InternalSearchPostProcessor.from_settings",
        return_value=mock_pp,
    )


def _make_identity(company_id: str = "company-1", user_id: str = "user-1"):
    settings = MagicMock()
    settings.authcontext.get_confidential_company_id.return_value = company_id
    settings.authcontext.get_confidential_user_id.return_value = user_id
    return settings


def _patch_identity():
    """Per-request identity resolves in-body via unique_mcp; return a stub."""
    return patch(
        "kb_mcp.tools.search.tool.get_unique_settings_async",
        new=AsyncMock(return_value=_make_identity()),
    )


def _patch_is_unique_ai_client(value: bool):
    """Stub node-chat-vs-generic-client detection (see is_unique_ai_client)."""
    return patch("kb_mcp.tools.search.tool.is_unique_ai_client", return_value=value)


def _patch_kb_settings(base_url: str | None = None, lookup_concurrency: int = 8):
    mock_settings = MagicMock()
    mock_settings.frontend_base_url_str.return_value = base_url
    mock_settings.scope_lookup_concurrency = lookup_concurrency
    return patch("kb_mcp.tools.search.tool.get_settings", return_value=mock_settings)


def _patch_resolve_scope_ids(mapping: dict[str, str] | None = None):
    return patch(
        "kb_mcp.tools.search.tool.resolve_scope_ids",
        new=AsyncMock(return_value=mapping or {}),
    )


@pytest.mark.asyncio
async def test_search_string_becomes_the_search_query():
    chunks = [_make_chunk("result A")]
    mock_service = MagicMock()
    mock_service.bind_settings.return_value = mock_service
    mock_service.state = MagicMock()
    mock_service.run = AsyncMock(return_value=MagicMock())

    with (
        patch(
            "kb_mcp.tools.search.tool.KnowledgeBaseInternalSearchService.from_config",
            return_value=mock_service,
        ),
        _patch_post_processor(chunks),
        _patch_identity(),
        _patch_kb_settings(None),
        _patch_resolve_scope_ids(),
    ):
        result = await search(
            search_string="test query",
            config=SearchToolConfig(),
        )

    # The only way search_string reaches the retrieval backend, given the
    # backend itself is mocked out here — this is the resulting query state,
    # not an assertion on which collaborator got called.
    assert mock_service.state.search_queries == ["test query"]
    assert isinstance(result, ToolResult)
    # result chunks + trailing citation instruction
    assert len(result.content) == 2


@pytest.mark.asyncio
async def test_logs_never_contain_raw_user_or_company_id(caplog):
    """user_id/company_id are confidential; logs must carry a correlation
    id derived from them, never the raw values."""
    chunks = [_make_chunk("result A")]
    mock_service = MagicMock()
    mock_service.bind_settings.return_value = mock_service
    mock_service.state = MagicMock()
    mock_service.run = AsyncMock(return_value=MagicMock())

    with (
        caplog.at_level(logging.INFO, logger="kb_mcp"),
        patch(
            "kb_mcp.tools.search.tool.KnowledgeBaseInternalSearchService.from_config",
            return_value=mock_service,
        ),
        _patch_post_processor(chunks),
        _patch_identity(),
        _patch_kb_settings(None),
        _patch_resolve_scope_ids(),
    ):
        await search(search_string="test query", config=SearchToolConfig())

    assert caplog.records, "expected at least one log record"
    for record in caplog.records:
        assert "user-1" not in record.getMessage()
        assert "company-1" not in record.getMessage()


@pytest.mark.asyncio
async def test_search_uses_defaults_when_no_config_provided():
    chunks = [_make_chunk("default")]
    mock_service = MagicMock()
    mock_service.bind_settings.return_value = mock_service
    mock_service.state = MagicMock()
    mock_service.run = AsyncMock(return_value=MagicMock())

    with (
        patch(
            "kb_mcp.tools.search.tool.KnowledgeBaseInternalSearchService.from_config",
            return_value=mock_service,
        ),
        _patch_post_processor(chunks),
        _patch_identity(),
        _patch_kb_settings(None),
        _patch_resolve_scope_ids(),
    ):
        result = await search(
            search_string="fallback query",
            config=SearchToolConfig(),
        )

    assert isinstance(result, ToolResult)
    assert mock_service.state.search_queries == ["fallback query"]


@pytest.mark.asyncio
async def test_search_returns_error_result_on_service_failure():
    with (
        patch(
            "kb_mcp.tools.search.tool.KnowledgeBaseInternalSearchService.from_config",
            side_effect=RuntimeError("KB unavailable"),
        ),
        _patch_identity(),
    ):
        result = await search(
            search_string="query",
            config=SearchToolConfig(),
        )

    assert result.is_error is True
    assert "KB unavailable" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_search_returns_error_result_on_post_processor_failure():
    mock_service = MagicMock()
    mock_service.bind_settings.return_value = mock_service
    mock_service.state = MagicMock()
    mock_service.run = AsyncMock(return_value=MagicMock())

    mock_pp = MagicMock()
    mock_pp.process = AsyncMock(side_effect=RuntimeError("post-processor failed"))

    with (
        patch(
            "kb_mcp.tools.search.tool.KnowledgeBaseInternalSearchService.from_config",
            return_value=mock_service,
        ),
        patch(
            "kb_mcp.tools.search.tool.InternalSearchPostProcessor.from_settings",
            return_value=mock_pp,
        ),
        _patch_identity(),
    ):
        result = await search(
            search_string="query",
            config=SearchToolConfig(),
        )

    assert result.is_error is True
    assert "post-processor failed" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_search_returns_error_when_identity_unresolvable():
    with patch(
        "kb_mcp.tools.search.tool.get_unique_settings_async",
        new=AsyncMock(side_effect=ValueError("Refusing to fall back to UNIQUE_AUTH_")),
    ):
        result = await search(
            search_string="query",
            config=SearchToolConfig(),
        )

    assert result.is_error is True
    assert "UNIQUE_AUTH_" in result.content[0].text  # type: ignore[union-attr]


def test_is_unique_ai_client_true_for_node_chats_own_client_name():
    ctx = MagicMock()
    ctx.session.client_params.clientInfo.name = "unique-ai-mcp-client-module-kb-mcp"
    with patch("kb_mcp.references.get_context", return_value=ctx):
        assert is_unique_ai_client() is True


def test_is_unique_ai_client_false_for_generic_client_name():
    ctx = MagicMock()
    ctx.session.client_params.clientInfo.name = "claude-code"
    with patch("kb_mcp.references.get_context", return_value=ctx):
        assert is_unique_ai_client() is False


def test_is_unique_ai_client_false_when_no_context():
    with patch("kb_mcp.references.get_context", side_effect=RuntimeError):
        assert is_unique_ai_client() is False


def test_is_unique_ai_client_false_when_client_params_missing():
    ctx = MagicMock()
    ctx.session.client_params = None
    with patch("kb_mcp.references.get_context", return_value=ctx):
        assert is_unique_ai_client() is False


def test_scope_id_from_folder_id_path_takes_leaf():
    assert scope_id_from_folder_id_path("uniquepathid://scope_a/scope_b") == "scope_b"


def test_frontend_document_url_shape():
    url = frontend_document_url(
        "https://example.unique.app",
        "scope_uy3cznkuysy3gasrxx2m4ezb",
        "cont_mvkp2iv25xy4cxccpq6i6byk",
    )
    assert url == (
        "https://example.unique.app/knowledge-upload/"
        "scope_uy3cznkuysy3gasrxx2m4ezb?file=cont_mvkp2iv25xy4cxccpq6i6byk"
    )


def test_reference_url_internal_content_uses_unique_scheme():
    chunk = _make_chunk("text")
    assert reference_url(chunk) == "unique://content/cont_abcdefgehijklmnopqrstuvwx"


def test_reference_url_builds_frontend_deep_link_when_configured():
    chunk = _make_chunk(
        "text",
        metadata=ContentMetadata(
            key="doc.pdf",
            mime_type="application/pdf",
            folderIdPath="uniquepathid://scope_root/scope_leaf",  # type: ignore[call-arg]
        ),
    )
    assert reference_url(chunk, frontend_base_url="https://example.unique.app") == (
        "https://example.unique.app/knowledge-upload/scope_leaf"
        "?file=cont_abcdefgehijklmnopqrstuvwx"
    )


def test_reference_url_internally_stored_web_chunk_uses_unique_scheme():
    chunk = _make_chunk(
        "text",
        url="https://example.com/doc",
        internally_stored_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert reference_url(chunk) == "unique://content/cont_abcdefgehijklmnopqrstuvwx"


def test_reference_url_external_chunk_keeps_original_url():
    chunk = _make_chunk("text", url="https://example.com/doc")
    assert reference_url(chunk) == "https://example.com/doc"


def test_markdown_citation_link_escapes_sm_folder_path():
    """Primary Fix 3 fixture matching the Unique AI stringified paste."""
    path = "[" + "SM" + "]/AlpenSys/Audit_Report_AlpenSys_FY2023.pdf"
    link = markdown_citation_link(
        path, "unique://content/cont_ioi3voailf7hr011zcp6b7eh"
    )
    assert link == (
        "[\\[SM\\]/AlpenSys/Audit_Report_AlpenSys_FY2023.pdf]"
        "(unique://content/cont_ioi3voailf7hr011zcp6b7eh)"
    )
    assert not link.startswith("[[")


def test_chunk_to_text_content_escapes_brackets_in_title():
    title = "[" + "SM" + "]/AlpenSys/notes.txt"
    chunk = _make_chunk(
        "body",
        title=title,
        chunk_id="chunk_abcdefgehijklmnopqrstuv",
    )
    content = chunk_to_text_content(chunk, sequence_number=1)
    assert content.text.startswith(
        "[\\[SM\\]/AlpenSys/notes.txt]"
        "(unique://content/cont_abcdefgehijklmnopqrstuvwx)\n"
    )


def test_chunk_to_text_content_has_markdown_link_header_and_reference_meta():
    chunk = _make_chunk(
        "The revenue grew by 12%.",
        title="Annual Report 2025",
        chunk_id="chunk_abcdefgehijklmnopqrstuv",
        start_page=12,
        end_page=14,
    )

    content = chunk_to_text_content(chunk, sequence_number=3)

    assert content.text.startswith(
        "[Annual Report 2025](unique://content/cont_abcdefgehijklmnopqrstuvwx)"
        " (pages 12-14)\n"
    )
    assert content.text.endswith("The revenue grew by 12%.")
    assert "[source" not in content.text

    assert content.meta is not None
    reference = content.meta[REFERENCE_META_KEY]
    assert reference["url"] == "unique://content/cont_abcdefgehijklmnopqrstuvwx"
    assert reference["sequenceNumber"] == 3
    assert reference["source"] == "node-ingestion-chunks"
    assert (
        reference["sourceId"]
        == "cont_abcdefgehijklmnopqrstuvwx_chunk_abcdefgehijklmnopqrstuv"
    )


def test_chunk_to_text_content_uses_frontend_url_in_text_but_unique_in_meta():
    chunk = _make_chunk(
        "body",
        title="CV.pdf",
        id="cont_mvkp2iv25xy4cxccpq6i6byk",
    )
    content = chunk_to_text_content(
        chunk,
        sequence_number=1,
        frontend_base_url="https://example.unique.app",
        scope_id="scope_uy3cznkuysy3gasrxx2m4ezb",
    )
    assert (
        "https://example.unique.app/knowledge-upload/"
        "scope_uy3cznkuysy3gasrxx2m4ezb?file=cont_mvkp2iv25xy4cxccpq6i6byk"
    ) in content.text
    assert content.meta is not None
    assert (
        content.meta[REFERENCE_META_KEY]["url"]
        == "unique://content/cont_mvkp2iv25xy4cxccpq6i6byk"
    )


@pytest.mark.asyncio
async def test_search_results_are_numbered_sequentially_and_include_citation_block():
    chunks = [_make_chunk("first"), _make_chunk("second")]
    mock_service = MagicMock()
    mock_service.bind_settings.return_value = mock_service
    mock_service.state = MagicMock()
    mock_service.run = AsyncMock(return_value=MagicMock())

    with (
        patch(
            "kb_mcp.tools.search.tool.KnowledgeBaseInternalSearchService.from_config",
            return_value=mock_service,
        ),
        _patch_post_processor(chunks),
        _patch_identity(),
        _patch_kb_settings(None),
        _patch_resolve_scope_ids(),
    ):
        result = await search(
            search_string="query",
            config=SearchToolConfig(),
        )

    texts = [c.text for c in result.content]  # type: ignore[union-attr]
    assert texts[0].startswith("[")
    assert "](unique://content/" in texts[0]
    assert "](unique://content/" in texts[1]
    assert "[source" not in texts[0]
    assert texts[2] == GENERIC_RESULT_CITATION_INSTRUCTION


@pytest.mark.asyncio
async def test_search_uses_sourceN_citation_instruction_when_called_via_unique_ai_chat():
    """Generic MCP clients (Claude Desktop/Code, Inspector) get the
    markdown-link instruction above; a call relayed through node-chat (its
    own MCP `clientInfo`, per is_unique_ai_client) must get the [sourceN]
    instruction instead — that's the only form the platform's
    citation-badge rendering resolves.
    """
    chunks = [_make_chunk("first"), _make_chunk("second")]
    mock_service = MagicMock()
    mock_service.bind_settings.return_value = mock_service
    mock_service.state = MagicMock()
    mock_service.run = AsyncMock(return_value=MagicMock())

    with (
        patch(
            "kb_mcp.tools.search.tool.KnowledgeBaseInternalSearchService.from_config",
            return_value=mock_service,
        ),
        _patch_post_processor(chunks),
        _patch_identity(),
        _patch_kb_settings(None),
        _patch_resolve_scope_ids(),
        _patch_is_unique_ai_client(True),
    ):
        result = await search(
            search_string="query",
            config=SearchToolConfig(),
        )

    texts = [c.text for c in result.content]  # type: ignore[union-attr]
    assert texts[2] == UNIQUE_AI_RESULT_CITATION_INSTRUCTION
    assert texts[2] != GENERIC_RESULT_CITATION_INSTRUCTION


@pytest.mark.asyncio
async def test_search_uses_frontend_deep_links_when_scopes_resolved():
    chunks = [
        _make_chunk("first", id="cont_aaaaaaaaaaaaaaaaaaaaaaa1", title="A.pdf"),
    ]
    mock_service = MagicMock()
    mock_service.bind_settings.return_value = mock_service
    mock_service.state = MagicMock()
    mock_service.run = AsyncMock(return_value=MagicMock())

    with (
        patch(
            "kb_mcp.tools.search.tool.KnowledgeBaseInternalSearchService.from_config",
            return_value=mock_service,
        ),
        _patch_post_processor(chunks),
        _patch_identity(),
        _patch_kb_settings("https://example.unique.app"),
        _patch_resolve_scope_ids(
            {"cont_aaaaaaaaaaaaaaaaaaaaaaa1": "scope_uy3cznkuysy3gasrxx2m4ezb"}
        ),
    ):
        result = await search(
            search_string="query",
            config=SearchToolConfig(),
        )

    assert (
        "https://example.unique.app/knowledge-upload/"
        "scope_uy3cznkuysy3gasrxx2m4ezb?file=cont_aaaaaaaaaaaaaaaaaaaaaaa1"
    ) in result.content[0].text  # type: ignore[union-attr]
