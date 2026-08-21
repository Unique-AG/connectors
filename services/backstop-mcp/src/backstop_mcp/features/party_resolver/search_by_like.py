from collections.abc import Mapping

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver._party_search_types import candidates_from_resources
from backstop_mcp.features.party_resolver.api_responses import PartyAttributes
from backstop_mcp.features.party_resolver.internal_dto import PartyCandidate

# Organizations LIKE `name`. People-shaped collections reject `filter[name][like]` and
# accept `filter[lastName][like]` only.
_LIKE_FIELDS: Mapping[SearchType, str] = {
    "organizations": "name",
    "contacts": "lastName",
    "people": "lastName",
    "employees": "lastName",
}

_LIKE_PAGE_SIZE = 200
_LIKE_MAX_RECORDS = 200

# Plain assignment — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
_PartyResource = BackstopApiResource[PartyAttributes]


async def search_by_like(
    client: BackstopClient,
    *,
    search_type: SearchType,
    search: str,
) -> tuple[PartyCandidate, ...]:
    """Substring lookup via `filter[<field>][like]` when `/quick-search` returns nothing.

    `/quick-search` is prefix-anchored (`Dispersion` misses `Capstone Dispersion`). This is
    the fallback for a name that is not a prefix of the stored display name. One page is
    enough: more than `_LIKE_MAX_RECORDS` hits is already ambiguous.
    """
    field = _LIKE_FIELDS[search_type]
    page = await client.paginate(
        f"/{search_type}",
        schema=_PartyResource,
        params={f"filter[{field}][like]": search},
        page_size=_LIKE_PAGE_SIZE,
        max_records=_LIKE_MAX_RECORDS,
    )
    return candidates_from_resources(page.items, search_type=search_type)
