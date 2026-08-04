from __future__ import annotations

from collections.abc import Sequence
from typing import override

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool

from backstop_mcp.backstop_client import get_backstop_client
from backstop_mcp.custom_fields.registry import TOOL_ENTITY_GLOSSARY
from backstop_mcp.custom_fields.service import CustomFieldsService, get_custom_fields_service
from backstop_mcp.logging import get_logger

logger = get_logger(__name__)


async def _warm_from_caller(service: CustomFieldsService) -> None:
    """Fetch the schema using the listing caller's own credential.

    `tools/list` is authenticated (the whole MCP endpoint is), so a real client is available
    here — but only callers who find the snapshot missing or past its TTL pay for it, since it
    is shared across every user of one Backstop instance. Configure a service account
    (`BACKSTOP_SERVICE_USERNAME`) to move that cost to startup instead.

    Any failure is swallowed: the glossary is advisory, and no listing should break because
    schema enrichment couldn't run. Callers fall back to `resolve_custom_field`, which is
    what its docstring already tells them to do when the glossary is missing.
    """
    try:
        async with await get_backstop_client() as client:
            await service.ensure_fresh(client)
    except Exception:
        logger.warning("custom_fields.glossary.warm_failed", exc_info=True)


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

        # Cheap path first: a DB read needs no credential and no Backstop round trip.
        await service.load_cached()
        if not service.is_fresh:
            await _warm_from_caller(service)

        enriched: list[Tool] = []
        for tool in tools:
            entity_types = TOOL_ENTITY_GLOSSARY.get(tool.name)
            if not entity_types:
                enriched.append(tool)
                continue
            glossary = "".join(service.glossary_for(entity) for entity in entity_types)
            if not glossary:
                enriched.append(tool)
                continue
            base = tool.description or ""
            enriched.append(tool.model_copy(update={"description": base + glossary}))
        return enriched
