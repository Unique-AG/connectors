from with_intelligence_mcp.features.mandates.api_responses import MandateExtendedAttributes
from with_intelligence_mcp.features.mandates.fetch_mandates_for_investor import MANDATES_PATH
from with_intelligence_mcp.with_intelligence_client import (
    NotFound,
    WithIntelligenceClient,
    narrow_dict,
)


async def fetch_mandate(
    client: WithIntelligenceClient, mandate_id: int
) -> MandateExtendedAttributes | None:
    try:
        body = await client.get_json(f"{MANDATES_PATH}/{mandate_id}")
    except NotFound:
        return None
    return MandateExtendedAttributes.model_validate(narrow_dict(body))
