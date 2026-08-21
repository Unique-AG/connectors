from urllib.parse import quote

from backstop_mcp.backstop_client import BackstopApiResourceDocument, BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver.api_responses import PartyAttributes

# Plain assignment (not a `type` statement) — `schema=` needs a real class object, and a PEP 695
# type alias isn't assignable to `type[T]` even though it resolves to one at runtime.
_PartyResourceDocument = BackstopApiResourceDocument[PartyAttributes]


async def fetch_party_name(
    client: BackstopClient, *, search_type: SearchType, party_id: str
) -> str | None:
    """Look up just the display name for a known party id.

    Used to honour "every successful resolution echoes the resolved name + Party ID" on the
    trusted-`party_id` path, where no search ran and so no name was ever seen.
    """
    path = f"/{search_type}/{quote(party_id, safe='')}"
    document = await client.get(
        path,
        params={"fields": "name,firstName,lastName"},
        schema=_PartyResourceDocument,
    )
    return document.require_data(path=path).attributes.display_name()
