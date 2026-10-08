"""Display name for a known party id, read with the type's own sparse fieldset."""

from urllib.parse import quote

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver._party_search_types import PARTY_SPARSE_FIELDS
from backstop_mcp.features.party_resolver.api_responses import PartyAttributes

_PartyResourceDocument = BackstopApiSingleResourceDocument[PartyAttributes]


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
            # `/organizations` and `/contacts` 400 on firstName/lastName.
            params={"fields": PARTY_SPARSE_FIELDS[search_type]},
            schema=_PartyResourceDocument,
        )
        return document.data.attributes.display_name()
