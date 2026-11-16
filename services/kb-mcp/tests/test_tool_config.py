"""Tests for kb-mcp tool config resolution and deployment baseline merging."""

import json

import pytest
from pydantic import ValidationError
from unique_mcp.meta.keys import CONFIG_META_KEY
from unique_toolkit.content.smart_rules import uniqueql_to_dict

from kb_mcp.common.tool_config import (
    ResolvedToolConfig,
    _config_env_key,
    get_kb_tool_config,
    merge_tool_configs,
    resolve_tool_config,
)
from kb_mcp.tools.content_metadata.config import ContentMetadataToolConfig
from kb_mcp.tools.content_tree.config import ContentTreeToolConfig
from kb_mcp.tools.read_file.config import ReadFileToolConfig
from kb_mcp.tools.search.config import SearchToolConfig

pytestmark = pytest.mark.ai


class _MockServer:
    def __init__(self, name: str) -> None:
        self.name = name


def _set_meta(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    meta = None if payload is None else {CONFIG_META_KEY: payload}
    monkeypatch.setattr(
        "kb_mcp.common.tool_config.unique_injectors.get_request_meta",
        lambda: meta,
    )


def _set_server(monkeypatch: pytest.MonkeyPatch, name: str = "kb-mcp-test") -> None:
    monkeypatch.setattr(
        "kb_mcp.common.tool_config.fastmcp_deps.get_server",
        lambda: _MockServer(name),
    )


def test_resolve_tool_config_returns_defaults_when_both_sources_absent(monkeypatch):
    _set_server(monkeypatch)
    _set_meta(monkeypatch, None)

    resolved = resolve_tool_config(ReadFileToolConfig)

    assert isinstance(resolved, ResolvedToolConfig)
    assert resolved.env_config is None
    assert resolved.config == ReadFileToolConfig()


def test_env_key_precedence_prefers_server_prefixed_over_tool_only(monkeypatch):
    _set_server(monkeypatch, "Unique Knowledge Base Search MCP")
    _set_meta(monkeypatch, None)
    server_key = _config_env_key("Unique Knowledge Base Search MCP", ReadFileToolConfig)
    tool_key = _config_env_key(None, ReadFileToolConfig)
    monkeypatch.setenv(server_key, '{"max_tokens_per_call": 1500}')
    monkeypatch.setenv(tool_key, '{"max_tokens_per_call": 3000}')

    resolved = resolve_tool_config(ReadFileToolConfig)

    assert resolved.config.max_tokens_per_call == 1500
    assert resolved.env_config is not None
    assert resolved.env_config.max_tokens_per_call == 1500


def test_env_falls_back_to_tool_only_key_when_server_key_unset(monkeypatch):
    _set_server(monkeypatch, "Unique Knowledge Base Search MCP")
    _set_meta(monkeypatch, None)
    server_key = _config_env_key("Unique Knowledge Base Search MCP", ReadFileToolConfig)
    tool_key = _config_env_key(None, ReadFileToolConfig)
    monkeypatch.delenv(server_key, raising=False)
    monkeypatch.setenv(tool_key, '{"max_tokens_per_call": 2500}')

    resolved = resolve_tool_config(ReadFileToolConfig)

    assert resolved.config.max_tokens_per_call == 2500


def test_env_file_lookup_supports_environment_file_path(monkeypatch, tmp_path):
    _set_server(monkeypatch, "test-server")
    _set_meta(monkeypatch, None)
    env_key = _config_env_key("test-server", ReadFileToolConfig)
    monkeypatch.delenv(env_key, raising=False)
    env_file = tmp_path / "custom.env"
    env_file.write_text(f'{env_key}={{"max_tokens_per_call": 1200}}\n')
    monkeypatch.setenv("ENVIRONMENT_FILE_PATH", str(env_file))

    resolved = resolve_tool_config(ReadFileToolConfig)

    assert resolved.config.max_tokens_per_call == 1200


def test_missing_environment_file_path_does_not_fallback_to_cwd(monkeypatch, tmp_path):
    _set_server(monkeypatch, "test-server")
    _set_meta(monkeypatch, None)
    monkeypatch.chdir(tmp_path)
    env_key = _config_env_key("test-server", ReadFileToolConfig)
    monkeypatch.delenv(env_key, raising=False)
    (tmp_path / ".env").write_text(f'{env_key}={{"max_tokens_per_call": 1200}}\n')
    monkeypatch.setenv("ENVIRONMENT_FILE_PATH", str(tmp_path / "does-not-exist.env"))

    resolved = resolve_tool_config(ReadFileToolConfig)

    assert resolved.env_config is None
    assert resolved.config.max_tokens_per_call == 8000


def test_env_file_lookup_prefers_unique_mcp_env_over_dotenv(monkeypatch, tmp_path):
    _set_server(monkeypatch, "test-server")
    _set_meta(monkeypatch, None)
    monkeypatch.delenv("ENVIRONMENT_FILE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    env_key = _config_env_key("test-server", ReadFileToolConfig)
    monkeypatch.delenv(env_key, raising=False)
    (tmp_path / "unique_mcp.env").write_text(
        f'{env_key}={{"max_tokens_per_call": 900}}\n'
    )
    (tmp_path / ".env").write_text(f'{env_key}={{"max_tokens_per_call": 2000}}\n')

    resolved = resolve_tool_config(ReadFileToolConfig)

    assert resolved.config.max_tokens_per_call == 900


def test_request_meta_accepts_json_string_and_dict_and_rejects_invalid_shape(
    monkeypatch,
):
    _set_server(monkeypatch)
    _set_meta(monkeypatch, json.dumps({"max_tokens_per_call": 4000}))
    assert resolve_tool_config(ReadFileToolConfig).config.max_tokens_per_call == 4000

    _set_meta(monkeypatch, {"max_tokens_per_call": 3000})
    assert resolve_tool_config(ReadFileToolConfig).config.max_tokens_per_call == 3000

    _set_meta(monkeypatch, {"max_tokens_per_call": -1})
    with pytest.raises(ValidationError):
        resolve_tool_config(ReadFileToolConfig)


def test_absent_metadata_returns_env_config_without_duplication(monkeypatch):
    _set_server(monkeypatch)
    _set_meta(monkeypatch, None)
    env_filter = {"operator": "equals", "path": ["dept"], "value": "Legal"}
    monkeypatch.setenv(
        _config_env_key(None, ContentMetadataToolConfig),
        json.dumps({"metadata_filter": env_filter, "excluded_fields": ["secret"]}),
    )

    resolved = get_kb_tool_config(ContentMetadataToolConfig)()

    assert resolved.config is resolved.env_config
    assert uniqueql_to_dict(resolved.config.metadata_filter) == env_filter
    assert resolved.config.excluded_fields == ["secret"]


def test_partial_request_config_preserves_search_default_safety_filter(monkeypatch):
    _set_server(monkeypatch)
    _set_meta(monkeypatch, {"serviceConfig": {"filtering": {"limit": 42}}})

    resolved = resolve_tool_config(SearchToolConfig)

    assert resolved.config.service_config.filtering.limit == 42
    assert uniqueql_to_dict(resolved.config.service_config.metadata_filter) == {
        "operator": "isNotNull",
        "path": ["folderId"],
        "value": "",
    }


def test_null_request_metadata_filter_keeps_search_default_safety_filter(monkeypatch):
    _set_server(monkeypatch)
    _set_meta(monkeypatch, {"serviceConfig": {"metadataFilter": None}})

    resolved = resolve_tool_config(SearchToolConfig)

    assert uniqueql_to_dict(resolved.config.service_config.metadata_filter) == {
        "operator": "isNotNull",
        "path": ["folderId"],
        "value": "",
    }


def test_model_defaults_are_not_hard_ceilings_when_env_omits_them(monkeypatch):
    _set_server(monkeypatch)
    _set_meta(monkeypatch, {"max_tokens_per_call": 20000})
    assert resolve_tool_config(ReadFileToolConfig).config.max_tokens_per_call == 20000

    _set_meta(monkeypatch, {"max_values_per_field": 5000})
    assert (
        resolve_tool_config(ContentMetadataToolConfig).config.max_values_per_field
        == 5000
    )

    _set_meta(
        monkeypatch,
        {
            "serviceConfig": {"filtering": {"limit": 500}},
            "postProcessing": {"maxTokensForSources": 60000},
        },
    )
    search_cfg = resolve_tool_config(SearchToolConfig).config
    assert search_cfg.service_config.filtering.limit == 500
    assert search_cfg.post_processing.max_tokens_for_sources == 60000


def test_search_config_merge_enforces_env_restrictions_and_preserves_other_fields():
    env = SearchToolConfig.model_validate(
        {
            "service_config": {
                "search": {"search_type": "VECTOR", "search_language": "german"},
                "filtering": {"limit": 50, "score_threshold": 0.4},
                "scope_ids": ["scope_a", "scope_b"],
                "metadata_filter": {
                    "operator": "equals",
                    "path": ["dept"],
                    "value": "Legal",
                },
            },
            "post_processing": {
                "max_tokens_for_sources": 10000,
                "percentage_of_input_tokens_for_sources": 0.25,
            },
        }
    )
    meta = SearchToolConfig.model_validate(
        {
            "serviceConfig": {
                "search": {"searchType": "COMBINED"},
                "filtering": {"limit": 200, "scoreThreshold": 0.1},
                "scopeIds": ["scope_b", "scope_c"],
                "metadataFilter": {
                    "operator": "equals",
                    "path": ["region"],
                    "value": "EU",
                },
            },
            "postProcessing": {
                "maxTokensForSources": 50000,
                "percentageOfInputTokensForSources": 0.8,
            },
        }
    )

    merged = merge_tool_configs(
        SearchToolConfig, env_config=env, meta_config=meta
    ).config

    assert merged.service_config.filtering.limit == 50
    assert merged.service_config.scope_ids == ["scope_a", "scope_b"]
    assert uniqueql_to_dict(merged.service_config.metadata_filter) == {
        "and": [
            {"operator": "in", "path": ["folderId"], "value": ["scope_b", "scope_c"]},
            {"operator": "equals", "path": ["region"], "value": "EU"},
            {"operator": "equals", "path": ["dept"], "value": "Legal"},
        ]
    }
    assert merged.post_processing.max_tokens_for_sources == 10000
    assert merged.post_processing.percentage_of_input_tokens_for_sources == 0.25
    # Fields not covered by this ticket keep existing override/fallback behavior.
    assert merged.service_config.search.search_type.value == "COMBINED"
    assert merged.service_config.search.search_language == "german"
    assert merged.service_config.filtering.score_threshold == 0.1


def test_search_config_null_or_empty_meta_never_clears_env_scopes_or_filter():
    env = SearchToolConfig.model_validate(
        {
            "service_config": {
                "scope_ids": ["scope_a"],
                "metadata_filter": {
                    "operator": "equals",
                    "path": ["dept"],
                    "value": "Legal",
                },
            }
        }
    )
    for empty_scopes in (None, []):
        meta = SearchToolConfig.model_validate(
            {"serviceConfig": {"scopeIds": empty_scopes, "metadataFilter": None}}
        )
        merged = merge_tool_configs(
            SearchToolConfig, env_config=env, meta_config=meta
        ).config
        assert merged.service_config.scope_ids == ["scope_a"]
        assert uniqueql_to_dict(merged.service_config.metadata_filter) == {
            "operator": "equals",
            "path": ["dept"],
            "value": "Legal",
        }


def test_content_tree_config_merge_enforces_env_ceilings_and_ands_filters():
    env = ContentTreeToolConfig.model_validate(
        {
            "metadata_filter": {
                "operator": "equals",
                "path": ["dept"],
                "value": "Legal",
            },
            "default_limit": 20,
            "default_tree_limit": 200,
            "default_match_on": "key",
        }
    )
    meta = ContentTreeToolConfig.model_validate(
        {
            "metadata_filter": {
                "operator": "equals",
                "path": ["mimeType"],
                "value": "application/pdf",
            },
            "default_limit": 100,
            "default_tree_limit": 50,
            "default_case_sensitive": True,
        }
    )

    merged = merge_tool_configs(
        ContentTreeToolConfig, env_config=env, meta_config=meta
    ).config

    assert uniqueql_to_dict(merged.metadata_filter) == {
        "and": [
            {"operator": "equals", "path": ["mimeType"], "value": "application/pdf"},
            {"operator": "equals", "path": ["dept"], "value": "Legal"},
        ]
    }
    assert merged.default_limit == 20
    assert merged.default_tree_limit == 50
    assert merged.default_match_on == "key"
    assert merged.default_case_sensitive is True


def test_content_metadata_config_merge_enforces_filter_and_value_ceiling():
    env = ContentMetadataToolConfig.model_validate(
        {
            "metadata_filter": {
                "operator": "equals",
                "path": ["dept"],
                "value": "Legal",
            },
            "excluded_fields": ["secret"],
            "max_values_per_field": 50,
        }
    )
    meta = ContentMetadataToolConfig.model_validate(
        {
            "metadata_filter": None,
            "max_values_per_field": 500,
        }
    )

    merged = merge_tool_configs(
        ContentMetadataToolConfig, env_config=env, meta_config=meta
    ).config

    assert uniqueql_to_dict(merged.metadata_filter) == {
        "operator": "equals",
        "path": ["dept"],
        "value": "Legal",
    }
    assert merged.max_values_per_field == 50
    assert merged.excluded_fields == ["secret"]
