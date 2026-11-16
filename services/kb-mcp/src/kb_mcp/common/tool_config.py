"""Resolve kb-mcp tool config from the environment baseline and request metadata."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from dotenv import dotenv_values
from fastmcp.server import dependencies as fastmcp_deps
from pydantic import BaseModel
from unique_mcp import unique_injectors
from unique_mcp.meta.keys import CONFIG_META_KEY
from unique_mcp.util.find_env_file import find_env_file
from unique_toolkit.content.smart_rules import UniqueQL, parse_uniqueql

from kb_mcp.common.metadata_filter import merge_request_metadata_filter

if TYPE_CHECKING:
    from kb_mcp.tools.content_metadata.config import ContentMetadataToolConfig
    from kb_mcp.tools.content_tree.config import ContentTreeToolConfig
    from kb_mcp.tools.read_file.config import ReadFileToolConfig
    from kb_mcp.tools.search.config import SearchToolConfig


@dataclass(frozen=True, slots=True)
class ResolvedToolConfig[T: BaseModel]:
    """Merged tool config alongside the raw explicit environment baseline."""

    config: T
    env_config: T | None = None


def unwrap_tool_config[T: BaseModel](
    value: ResolvedToolConfig[T] | T,
) -> tuple[T, T | None]:
    if isinstance(value, ResolvedToolConfig):
        return value.config, value.env_config
    return value, None


def _config_env_key(server_name: str | None, config_model: type[BaseModel]) -> str:
    config_name = re.sub(r"Config$", "", config_model.__name__)
    config_snake = re.sub(r"(?<!^)(?=[A-Z])", "_", config_name).upper()
    if not server_name:
        return f"UNIQUE_MCP_TOOL_{config_snake}_CONFIG"
    server_part = re.sub(r"[^A-Za-z0-9]+", "_", server_name).strip("_").upper()
    if not server_part:
        return f"UNIQUE_MCP_TOOL_{config_snake}_CONFIG"
    return f"UNIQUE_MCP_TOOL_{server_part}_{config_snake}_CONFIG"


def _load_tool_config_override(env_key: str) -> str | None:
    if val := os.environ.get(env_key):
        return val
    env_path = os.environ.get("ENVIRONMENT_FILE_PATH")
    env_file = (
        env_path
        if env_path and Path(env_path).is_file()
        else find_env_file(filenames=["unique_mcp.env", ".env"], required=False)
    )
    return dotenv_values(env_file).get(env_key) if env_file else None


def _current_server_name() -> str | None:
    try:
        server = fastmcp_deps.get_server()
    except RuntimeError, LookupError:
        return None
    return server.name or None


def _load_env_config[T: BaseModel](config_model: type[T]) -> T | None:
    server_name = _current_server_name()
    candidates = (server_name, None) if server_name else (None,)
    for candidate in candidates:
        if env_val := _load_tool_config_override(
            _config_env_key(candidate, config_model)
        ):
            return config_model.model_validate_json(env_val)
    return None


def _load_request_meta_config[T: BaseModel](config_model: type[T]) -> T | None:
    raw = (unique_injectors.get_request_meta() or {}).get(CONFIG_META_KEY)
    if raw is None:
        return None
    if isinstance(raw, str):
        return config_model.model_validate_json(raw)
    return config_model.model_validate(raw)


def _overlay_explicit[M: BaseModel](base: M, override: M) -> M:
    updates = {field: getattr(override, field) for field in override.model_fields_set}
    return base.model_copy(update=updates) if updates else base


def _merge_ceiling[V: (int, float)](
    env_val: V, env_set: bool, meta_val: V, meta_set: bool
) -> V:
    if env_set and meta_set:
        return min(env_val, meta_val)
    return env_val if env_set else meta_val


def _merge_metadata_filter(
    env_filter: UniqueQL | None,
    meta_filter: UniqueQL | None,
) -> UniqueQL | None:
    if env_filter is not None and meta_filter is not None:
        merged = merge_request_metadata_filter(
            admin_metadata_filter=env_filter,
            llm_metadata_filter=meta_filter,
        )
        return parse_uniqueql(merged) if merged is not None else None
    return env_filter if env_filter is not None else meta_filter


def _merge_search_config(
    env: SearchToolConfig, meta: SearchToolConfig
) -> SearchToolConfig:
    env_sc = env.service_config
    meta_sc = meta.service_config
    env_has_sc = "service_config" in env.model_fields_set
    meta_has_sc = "service_config" in meta.model_fields_set

    merged_search = (
        _overlay_explicit(env_sc.search, meta_sc.search)
        if meta_has_sc and "search" in meta_sc.model_fields_set
        else env_sc.search
    )

    merged_filtering = (
        _overlay_explicit(env_sc.filtering, meta_sc.filtering)
        if meta_has_sc and "filtering" in meta_sc.model_fields_set
        else env_sc.filtering
    )
    if (
        env_has_sc
        and "filtering" in env_sc.model_fields_set
        and "limit" in env_sc.filtering.model_fields_set
    ):
        meta_limit_set = (
            meta_has_sc
            and "filtering" in meta_sc.model_fields_set
            and "limit" in meta_sc.filtering.model_fields_set
        )
        merged_filtering = merged_filtering.model_copy(
            update={
                "limit": _merge_ceiling(
                    env_sc.filtering.limit,
                    True,
                    meta_sc.filtering.limit,
                    meta_limit_set,
                )
            }
        )

    env_has_filter = (
        env_has_sc
        and "metadata_filter" in env_sc.model_fields_set
        and env_sc.metadata_filter is not None
    )
    meta_has_filter = meta_has_sc and "metadata_filter" in meta_sc.model_fields_set
    if env_has_filter:
        merged_filter = _merge_metadata_filter(
            env_sc.metadata_filter,
            meta_sc.metadata_filter if meta_has_filter else None,
        )
    elif meta_has_filter and meta_sc.metadata_filter is not None:
        merged_filter = meta_sc.metadata_filter
    else:
        merged_filter = env_sc.metadata_filter

    env_scopes = env_sc.scope_ids if env_has_sc and env_sc.scope_ids else None
    meta_scopes = meta_sc.scope_ids if meta_has_sc and meta_sc.scope_ids else None
    if env_scopes:
        merged_scopes: list[str] | None = env_scopes
        if meta_scopes and set(meta_scopes) != set(env_scopes):
            combined = merge_request_metadata_filter(
                admin_metadata_filter=merged_filter,
                admin_scope_ids=meta_scopes,
            )
            merged_filter = parse_uniqueql(combined) if combined is not None else None
    elif meta_has_sc and "scope_ids" in meta_sc.model_fields_set:
        merged_scopes = meta_sc.scope_ids
    else:
        merged_scopes = env_sc.scope_ids

    merged_reranker = (
        meta_sc.reranker_config
        if meta_has_sc and "reranker_config" in meta_sc.model_fields_set
        else env_sc.reranker_config
    )
    merged_sc = env_sc.model_copy(
        update={
            "search": merged_search,
            "filtering": merged_filtering,
            "scope_ids": merged_scopes,
            "metadata_filter": merged_filter,
            "reranker_config": merged_reranker,
        }
    )

    env_pp = env.post_processing
    meta_pp = meta.post_processing
    meta_has_pp = "post_processing" in meta.model_fields_set
    merged_pp = _overlay_explicit(env_pp, meta_pp) if meta_has_pp else env_pp
    if "post_processing" in env.model_fields_set:
        pp_updates: dict[str, int | float] = {}
        if "max_tokens_for_sources" in env_pp.model_fields_set:
            pp_updates["max_tokens_for_sources"] = _merge_ceiling(
                env_pp.max_tokens_for_sources,
                True,
                meta_pp.max_tokens_for_sources,
                meta_has_pp and "max_tokens_for_sources" in meta_pp.model_fields_set,
            )
        if "percentage_of_input_tokens_for_sources" in env_pp.model_fields_set:
            pp_updates["percentage_of_input_tokens_for_sources"] = _merge_ceiling(
                env_pp.percentage_of_input_tokens_for_sources,
                True,
                meta_pp.percentage_of_input_tokens_for_sources,
                meta_has_pp
                and "percentage_of_input_tokens_for_sources"
                in meta_pp.model_fields_set,
            )
        if pp_updates:
            merged_pp = merged_pp.model_copy(update=pp_updates)

    return env.model_copy(
        update={"service_config": merged_sc, "post_processing": merged_pp}
    )


def _merge_content_tree_config(
    env: ContentTreeToolConfig, meta: ContentTreeToolConfig
) -> ContentTreeToolConfig:
    merged = _overlay_explicit(env, meta)
    updates: dict[str, object] = {
        "metadata_filter": _merge_metadata_filter(
            env.metadata_filter,
            meta.metadata_filter
            if "metadata_filter" in meta.model_fields_set
            else None,
        )
    }
    if "default_limit" in env.model_fields_set:
        updates["default_limit"] = _merge_ceiling(
            env.default_limit,
            True,
            meta.default_limit,
            "default_limit" in meta.model_fields_set,
        )
    if "default_tree_limit" in env.model_fields_set:
        updates["default_tree_limit"] = _merge_ceiling(
            env.default_tree_limit,
            True,
            meta.default_tree_limit,
            "default_tree_limit" in meta.model_fields_set,
        )
    return merged.model_copy(update=updates)


def _merge_content_metadata_config(
    env: ContentMetadataToolConfig, meta: ContentMetadataToolConfig
) -> ContentMetadataToolConfig:
    merged = _overlay_explicit(env, meta)
    updates: dict[str, object] = {
        "metadata_filter": _merge_metadata_filter(
            env.metadata_filter,
            meta.metadata_filter
            if "metadata_filter" in meta.model_fields_set
            else None,
        )
    }
    if "max_values_per_field" in env.model_fields_set:
        updates["max_values_per_field"] = _merge_ceiling(
            env.max_values_per_field,
            True,
            meta.max_values_per_field,
            "max_values_per_field" in meta.model_fields_set,
        )
    return merged.model_copy(update=updates)


def _merge_read_file_config(
    env: ReadFileToolConfig, meta: ReadFileToolConfig
) -> ReadFileToolConfig:
    if "max_tokens_per_call" in env.model_fields_set:
        return env.model_copy(
            update={
                "max_tokens_per_call": _merge_ceiling(
                    env.max_tokens_per_call,
                    True,
                    meta.max_tokens_per_call,
                    "max_tokens_per_call" in meta.model_fields_set,
                )
            }
        )
    return meta


def merge_tool_configs[T: BaseModel](
    config_model: type[T],
    *,
    env_config: T | None,
    meta_config: T | None,
) -> ResolvedToolConfig[T]:
    if env_config is None and meta_config is None:
        return ResolvedToolConfig(config=config_model(), env_config=None)
    if meta_config is None:
        assert env_config is not None
        return ResolvedToolConfig(config=env_config, env_config=env_config)
    from kb_mcp.tools.content_metadata.config import ContentMetadataToolConfig
    from kb_mcp.tools.content_tree.config import ContentTreeToolConfig
    from kb_mcp.tools.read_file.config import ReadFileToolConfig
    from kb_mcp.tools.search.config import SearchToolConfig

    if env_config is None:
        if (
            isinstance(meta_config, SearchToolConfig)
            and meta_config.service_config.metadata_filter is None
            and not meta_config.service_config.scope_ids
        ):
            default_filter = SearchToolConfig().service_config.metadata_filter
            meta_config = cast(
                T,
                meta_config.model_copy(
                    update={
                        "service_config": meta_config.service_config.model_copy(
                            update={"metadata_filter": default_filter}
                        )
                    }
                ),
            )
        return ResolvedToolConfig(config=meta_config, env_config=None)

    if isinstance(env_config, SearchToolConfig) and isinstance(
        meta_config, SearchToolConfig
    ):
        merged: BaseModel = _merge_search_config(env_config, meta_config)
    elif isinstance(env_config, ContentTreeToolConfig) and isinstance(
        meta_config, ContentTreeToolConfig
    ):
        merged = _merge_content_tree_config(env_config, meta_config)
    elif isinstance(env_config, ContentMetadataToolConfig) and isinstance(
        meta_config, ContentMetadataToolConfig
    ):
        merged = _merge_content_metadata_config(env_config, meta_config)
    elif isinstance(env_config, ReadFileToolConfig) and isinstance(
        meta_config, ReadFileToolConfig
    ):
        merged = _merge_read_file_config(env_config, meta_config)
    else:
        raise TypeError(f"Unsupported tool config model: {config_model.__name__}")
    return ResolvedToolConfig(config=cast(T, merged), env_config=env_config)


def resolve_tool_config[T: BaseModel](config_model: type[T]) -> ResolvedToolConfig[T]:
    return merge_tool_configs(
        config_model,
        env_config=_load_env_config(config_model),
        meta_config=_load_request_meta_config(config_model),
    )


def get_kb_tool_config[T: BaseModel](
    config_model: type[T],
) -> Callable[[], ResolvedToolConfig[T]]:
    def _inner() -> ResolvedToolConfig[T]:
        return resolve_tool_config(config_model)

    return _inner
