from collections.abc import Mapping

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver._party_search_types import (
    PARTY_SPARSE_FIELDS,
    candidates_from_resources,
)
from backstop_mcp.features.party_resolver.api_responses import PartyAttributes
from backstop_mcp.features.party_resolver.internal_dto import PartyCandidate

# Organizations LIKE `name`. People and employees reject `filter[name][like]` and accept
# `filter[lastName][like]` only. `/contacts` is a mixed party table: both `name` and
# `lastName` filters 400, so contacts have no LIKE fallback — empty quick-search is not-found.
_LIKE_FIELDS: Mapping[SearchType, str] = {
    "organizations": "name",
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
    field = _LIKE_FIELDS.get(search_type)
    if field is None:
        return ()
    page = await client.paginate(
        f"/{search_type}",
        schema=_PartyResource,
        params={
            f"filter[{field}][like]": search,
            f"fields[{search_type}]": PARTY_SPARSE_FIELDS[search_type],
        },
        page_size=_LIKE_PAGE_SIZE,
        max_records=_LIKE_MAX_RECORDS,
    )
    return candidates_from_resources(page.items, search_type=search_type)
