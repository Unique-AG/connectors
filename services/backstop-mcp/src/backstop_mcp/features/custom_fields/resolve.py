"""Resolve a custom-field name against the schema cache.

The counterpart to `party_resolver.resolve`: freshness + index lookup + the shared ambiguity
policy. `CustomFieldsService` owns only the cache; elicitation lives here so a schema store
never prompts the user.
"""

from fastmcp import Context

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.custom_fields.index import FieldResolution, resolve_in_index
from backstop_mcp.features.custom_fields.service import CustomFieldsService
from backstop_mcp.features.resolution import Ambiguous, elicit_choice


async def resolve_field(
    service: CustomFieldsService,
    client: BackstopClient,
    *,
    entity_type: str,
    query: str,
    refresh: bool = False,
    ctx: Context | None = None,
) -> FieldResolution:
    """Resolve one field by name, applying the shared ambiguity policy.

    When `ctx` is supplied and several fields match, the user is asked to pick one — the same
    policy party resolution uses (see `resolution.py`). Without a `ctx` the ambiguity is
    returned for the caller to surface.
    """
    if refresh:
        await service.refresh(client)
    else:
        await service.ensure_fresh(client)

    result = resolve_in_index(service.index, entity_type=entity_type, query=query)
    if ctx is not None and isinstance(result, Ambiguous):
        return await elicit_choice(
            ctx,
            result,
            prompt=(
                f'Several {result.scope} fields matched "{result.query}". '
                + "Which one did you mean?"
            ),
        )
    return result
