from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver._party_search_types import (
    BACKSTOP_SEARCH_TYPES,
    PartyCollectionDocument,
    candidates_from_document,
)
from backstop_mcp.features.party_resolver.internal_dto import PartyCandidate, QuickSearchOptionsDto


async def quick_search(
    client: BackstopClient,
    *,
    search_type: SearchType,
    search: str,
    options: QuickSearchOptionsDto | None = None,
) -> tuple[PartyCandidate, ...]:
    """Fuzzy/name lookup via `GET /quick-search`, pinned to a single `search_type`.

    Prefix-anchored: `Dispersion` misses `Capstone Dispersion`; `Capstone Disp` hits.
    Collection filters also accept `like` (`filter[name][like]` on organizations,
    `filter[lastName][like]` on people) — `resolve_party` falls back to those when this
    returns nothing. `eq` on a partial display name still misses.

    Never sends Backstop's `EMAIL_ADDRESS` search type: `resolve_party` routes email-looking
    input to `search_by_email` before reaching here, so this path only ever sees a name.
    """
    resolved_options = options if options is not None else QuickSearchOptionsDto()
    response = await client.get(
        "/quick-search",
        params=_quick_search_params(
            search_type=search_type,
            search=search,
            options=resolved_options,
        ),
        schema=PartyCollectionDocument,
    )
    return candidates_from_document(response, search_type=search_type)


def _quick_search_params(
    *,
    search_type: SearchType,
    search: str,
    options: QuickSearchOptionsDto,
) -> dict[str, object]:
    params: dict[str, object] = {
        "filter[searchText][eq]": search,
        "filter[searchTypes][eq]": BACKSTOP_SEARCH_TYPES[search_type],
        "filter[limit][eq]": options.limit,
        "filter[showAll][eq]": options.show_all,
        "filter[enhanceSearchTypes][eq]": options.enhance_search_types,
        "page[limit]": options.limit,
        "page[offset]": 0,
    }

    if options.full_email_match is not None:
        params["filter[fullEmailMatch][eq]"] = options.full_email_match

    if options.filter_type is not None:
        params["filter[filterType][eq]"] = options.filter_type

    return params
