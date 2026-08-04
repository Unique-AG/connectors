from __future__ import annotations

from collections.abc import Sequence
from typing import override

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool

from backstop_mcp.custom_fields.registry import TOOL_ENTITY_GLOSSARY
from backstop_mcp.custom_fields.service import get_custom_fields_service


class CustomFieldGlossaryMiddleware(Middleware):
    """Append per-entity custom-field glossaries to tool descriptions on tools/list."""

    @override
    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        service = get_custom_fields_service()

        # Best-effort: use in-memory/overrides state without requiring auth on list.
        await service.ensure_loaded(client=None)

        enriched: list[Tool] = []
        for tool in tools:
            entity_types = TOOL_ENTITY_GLOSSARY.get(tool.name)
            if not entity_types:
                enriched.append(tool)
                continue
            glossary = "".join(service.glossary_for(entity) for entity in entity_types)
            base = tool.description or ""
            enriched.append(tool.model_copy(update={"description": base + glossary}))
        return enriched
