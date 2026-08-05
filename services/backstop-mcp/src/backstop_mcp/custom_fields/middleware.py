from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import ClassVar, override

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool

from backstop_mcp.custom_fields.glossary import format_glossaries
from backstop_mcp.custom_fields.service import CustomFieldsService
from backstop_mcp.logging import get_logger
from backstop_mcp.runtime import get_backstop_client, get_custom_fields_service
from backstop_mcp.tools.registry import glossary_entities_by_tool_name

logger = get_logger(__name__)


class CustomFieldGlossaryMiddleware(Middleware):
    """Append per-entity custom-field glossaries to tool descriptions on tools/list."""

    # How long to stop attempting a schema warm after one fails. Without it, a Backstop outage
    # makes every tools/list wait out a full upstream timeout for a glossary that is advisory.
    WARM_FAILURE_COOLDOWN: ClassVar[timedelta] = timedelta(minutes=5)

    def __init__(self) -> None:
        super().__init__()
        self._warm_failed_at: datetime | None = None

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
            await self._warm(service)

        scopes = glossary_entities_by_tool_name()
        enriched: list[Tool] = []
        for tool in tools:
            entity_types = scopes.get(tool.name)
            if not entity_types:
                enriched.append(tool)
                continue
            glossary = format_glossaries(
                [(entity, service.definitions_for(entity)) for entity in entity_types]
            )
            if not glossary:
                enriched.append(tool)
                continue
            enriched.append(
                tool.model_copy(update={"description": (tool.description or "") + glossary})
            )
        return enriched

    async def _warm(self, service: CustomFieldsService) -> None:
        """Fetch the schema using the listing caller's own credential.

        `tools/list` is authenticated (the whole MCP endpoint is), so a real client is available
        here — but only callers who find the snapshot missing or past its TTL pay for it, since it
        is shared across every user of one Backstop instance. Configure a service account
        (`BACKSTOP_SERVICE_USERNAME`) to move that cost to startup instead.

        Any failure is swallowed: the glossary is advisory, and no listing should break because
        schema enrichment couldn't run. Callers fall back to `resolve_custom_field`, which is
        what its docstring already tells them to do when the glossary is missing.
        """
        if self._in_failure_cooldown():
            return
        try:
            client = await get_backstop_client()
            await service.ensure_fresh(client)
        except Exception:
            self._warm_failed_at = datetime.now(UTC)
            logger.warning("custom_fields.glossary.warm_failed", exc_info=True)

    def _in_failure_cooldown(self) -> bool:
        if self._warm_failed_at is None:
            return False
        if datetime.now(UTC) - self._warm_failed_at < self.WARM_FAILURE_COOLDOWN:
            return True
        self._warm_failed_at = None
        return False
