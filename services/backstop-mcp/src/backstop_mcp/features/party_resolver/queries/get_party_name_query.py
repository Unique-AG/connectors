"""Display name for a known party id (`fields=name,firstName,lastName`)."""

from urllib.parse import quote

from backstop_mcp.backstop_client import BackstopApiResourceDocument, BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver.api_responses import PartyAttributes

_PartyResourceDocument = BackstopApiResourceDocument[PartyAttributes]


class GetPartyNameQuery:
    """Look up just the display name for a known party id.

    Used to honour "every successful resolution echoes the resolved name + Party ID" on the
    trusted-`party_id` path, where no search ran and so no name was ever seen.
    """

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(self, *, search_type: SearchType, party_id: str) -> str | None:
        path = f"/{search_type}/{quote(party_id, safe='')}"
        document = await self._client.get(
            path,
            params={"fields": "name,firstName,lastName"},
            schema=_PartyResourceDocument,
        )
        return document.require_data(path=path).attributes.display_name()
