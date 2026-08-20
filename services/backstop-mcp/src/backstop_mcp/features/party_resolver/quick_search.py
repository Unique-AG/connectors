from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver._party_search_types import (
    BACKSTOP_SEARCH_TYPES,
    PartyCollectionDocument,
    candidates_from_document,
    looks_like_email,
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

    The only fuzzy primitive Backstop offers: its filter operators are `eq, neq, gt, ge, lt, le`,
    so `filter[name][eq]=Capstone` returns nothing when the stored record is
    "Capstone Investment Advisors LP".
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
        "filter[searchTypes][eq]": _backstop_search_types(search_type=search_type, search=search),
        "filter[limit][eq]": options.limit,
        "filter[showAll][eq]": options.show_all,
        "filter[enhanceSearchTypes][eq]": options.enhance_search_types,
        "page[limit]": options.limit,
        "page[offset]": 0,
    }

    if options.full_email_match is None:
        if looks_like_email(search):
            params["filter[fullEmailMatch][eq]"] = True
    else:
        params["filter[fullEmailMatch][eq]"] = options.full_email_match

    if options.filter_type is not None:
        params["filter[filterType][eq]"] = options.filter_type

    return params


def _backstop_search_types(*, search_type: SearchType, search: str) -> str:
    """Map `search_type` to Backstop's uppercase `searchTypes` enum value(s).

    When `search` itself looks like an email, `EMAIL_ADDRESS` is added to the person-shaped
    mapping so a quick-search direct caller (unlike `resolve_party.py`'s `_resolve_one`, which
    routes email-looking input to `search_by_email` instead) still matches on it.
    """
    base = BACKSTOP_SEARCH_TYPES[search_type]
    if search_type != "organizations" and looks_like_email(search):
        return f"{base},EMAIL_ADDRESS"
    return base
