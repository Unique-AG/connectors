"""Append per-entity custom-field glossaries to tool descriptions on tools/list.

Scopes come from each tool's `meta["backstop.glossary_entities"]` (see
`features.custom_fields.glossary_meta`). Description length is capped both per glossary block
and across the whole tools/list payload.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import ClassVar, override

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool

from backstop_mcp.backstop_client import CallerClientProvider
from backstop_mcp.features.custom_fields import (
    DEFAULT_GLOSSARY_BUDGET_CHARS,
    CustomFieldsService,
    format_glossaries,
    parse_glossary_entities,
)

logger = logging.getLogger(__name__)

# Hard cap on the sum of all tool `description` strings returned from one tools/list.
# Keeps the listing usable when several tools each carry a glossary.
DEFAULT_TOOLS_LIST_DESCRIPTION_BUDGET_CHARS = 24_000


class CustomFieldGlossaryMiddleware(Middleware):
    """Append per-entity custom-field glossaries to tool descriptions on tools/list.

    Collaborators are injected by `create_app()`, not reached through `server.runtime`: unlike a
    tool function (whose signature FastMCP owns), middleware is constructed by us, so there is
    no reason for it to consult a process-wide global.
    """

    WARM_FAILURE_COOLDOWN: ClassVar[timedelta] = timedelta(minutes=5)

    def __init__(
        self,
        service: CustomFieldsService,
        *,
        client_for_caller: CallerClientProvider,
        glossary_budget_chars: int = DEFAULT_GLOSSARY_BUDGET_CHARS,
        tools_list_description_budget_chars: int = DEFAULT_TOOLS_LIST_DESCRIPTION_BUDGET_CHARS,
    ) -> None:
        super().__init__()
        self._service: CustomFieldsService = service
        self._client_for_caller: CallerClientProvider = client_for_caller
        self._glossary_budget_chars: int = glossary_budget_chars
        self._tools_list_description_budget_chars: int = tools_list_description_budget_chars
        self._warm_failed_at: datetime | None = None

    @override
    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        service = self._service

        await service.load_cached()
        if not service.is_fresh:
            await self._warm()

        enriched: list[Tool] = []
        remaining_total = self._tools_list_description_budget_chars
        for tool in tools:
            base = tool.description or ""
            if remaining_total <= 0:
                enriched.append(tool.model_copy(update={"description": ""}))
                continue
            if len(base) > remaining_total:
                enriched.append(tool.model_copy(update={"description": base[:remaining_total]}))
                remaining_total = 0
                continue

            entity_types = parse_glossary_entities(tool.meta)
            if not entity_types:
                enriched.append(tool)
                remaining_total -= len(base)
                continue

            glossary_budget = min(
                self._glossary_budget_chars,
                remaining_total - len(base),
            )
            glossary = ""
            if glossary_budget > 0:
                glossary = format_glossaries(
                    [
                        (entity.value, service.definitions_for(entity.value))
                        for entity in entity_types
                    ],
                    budget_chars=glossary_budget,
                )
            description = base + glossary
            if len(description) > remaining_total:
                description = description[:remaining_total]
            enriched.append(tool.model_copy(update={"description": description}))
            remaining_total -= len(description)
        return enriched

    async def _warm(self) -> None:
        """Fetch the schema using the listing caller's own credential.

        Any failure is swallowed: the glossary is advisory, and no listing should break because
        schema enrichment couldn't run. Callers fall back to `list_custom_fields` when the
        glossary is missing or truncated.
        """
        if self._in_failure_cooldown():
            return
        try:
            client = await self._client_for_caller()
            await self._service.ensure_fresh(client)
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
