"""Name/email/id → one party, or a batch of them."""

import asyncio
from collections.abc import Mapping, Sequence

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver._party_search_types import (
    BACKSTOP_SEARCH_TYPES,
    EMAIL_FIELDS,
    PARTY_SPARSE_FIELDS,
    PartyCollectionDocument,
    candidates_from_document,
    candidates_from_resources,
    normalized_email,
)
from backstop_mcp.features.party_resolver.api_responses import PartyAttributes
from backstop_mcp.features.party_resolver.internal_dto import (
    BatchPartyResolution,
    PartyCandidate,
    PartyResolution,
    PartyResolveItemDto,
    QuickSearchOptionsDto,
    ResolvedPartyDto,
)
from backstop_mcp.features.party_resolver.queries.get_party_name_query import GetPartyNameQuery
from backstop_mcp.features.resolution import Resolved, collect_batch, from_candidates

# Organizations LIKE `name`. People and employees reject `filter[name][like]` and accept
# `filter[lastName][like]` only. `/contacts` is a mixed party table: both `name` and
# `lastName` filters 400, so contacts have no LIKE fallback — empty quick-search is not-found.
_LIKE_FIELDS: Mapping[SearchType, str] = {
    "organizations": "name",
    "people": "lastName",
    "employees": "lastName",
}

_PartyResource = BackstopApiResource[PartyAttributes]


class ResolvePartyQuery:
    """Resolve a party from a name, an email, or a trusted Party ID."""

    def __init__(self, *, client: BackstopClient, get_party_name_query: GetPartyNameQuery) -> None:
        self._client: BackstopClient = client
        self._get_party_name_query: GetPartyNameQuery = get_party_name_query

    async def run(
        self,
        *,
        search_type: SearchType,
        party_id: str | None = None,
        search: str | None = None,
        name: str | None = None,
        confirm_name: bool = False,
        quick_search_options: QuickSearchOptionsDto | None = None,
    ) -> PartyResolution:
        """Resolve one party. Does not elicit — the tool asks when this returns Ambiguous.

        Set `confirm_name` when the caller has no other way to learn the party's name — it
        costs one extra `fields=name` request on the trusted-`party_id` path, and buys the
        echo that makes a wrong id visible instead of silent. Callers that fetch the record
        anyway (e.g. `get_organization`) leave it off and backfill from their own response.
        """
        return await self._resolve_one(
            search_type=search_type,
            item=PartyResolveItemDto(party_id=party_id, search=search, name=name),
            confirm_name=confirm_name,
            quick_search_options=quick_search_options,
        )

    async def run_batch(
        self,
        *,
        search_type: SearchType,
        items: Sequence[PartyResolveItemDto],
        confirm_name: bool = False,
        quick_search_options: QuickSearchOptionsDto | None = None,
    ) -> BatchPartyResolution:
        """Resolve several parties, returning one combined payload if anything is unresolved.

        Never elicits, by design: prompting per item is the "modal storm" the batch path
        exists to avoid, so the model is given every unresolved item at once (policy step 3
        in `resolution.py`).

        Items resolve concurrently — the per-user concurrency gate lives around each
        upstream request, so the fan-out queues against Backstop's limit instead of
        breaching it.
        """
        outcomes = await asyncio.gather(
            *(
                self._resolve_one(
                    search_type=search_type,
                    item=item,
                    confirm_name=confirm_name,
                    quick_search_options=quick_search_options,
                )
                for item in items
            )
        )
        return collect_batch(
            [
                (item.search or item.party_id or "", outcome)
                for item, outcome in zip(items, outcomes, strict=True)
            ]
        )

    async def _resolve_one(
        self,
        *,
        search_type: SearchType,
        item: PartyResolveItemDto,
        confirm_name: bool,
        quick_search_options: QuickSearchOptionsDto | None,
    ) -> PartyResolution:
        if item.party_id is not None:
            resolved_name = item.name
            if resolved_name is None and confirm_name:
                resolved_name = await self._get_party_name_query.run(
                    search_type=search_type, party_id=item.party_id
                )
            return Resolved(
                value=ResolvedPartyDto(
                    id=item.party_id, search_type=search_type, name=resolved_name
                )
            )

        assert item.search is not None
        email = normalized_email(item.search)
        if email is not None:
            candidates = await self._search_by_email(search_type=search_type, email=email)
        else:
            candidates = await self._quick_search(
                search_type=search_type,
                search=item.search,
                options=quick_search_options,
            )
            if not candidates:
                candidates = await self._search_by_like(search_type=search_type, search=item.search)

        return from_candidates(candidates, query=item.search, scope=search_type)

    async def _search_by_email(
        self, *, search_type: SearchType, email: str
    ) -> tuple[PartyCandidate, ...]:
        """Exact-match email lookup across the email fields applicable to `search_type`.

        Queries each field separately (never AND-ed) and dedupes hits by resource id.
        Backstop stores up to three addresses per person/employee, so checking only
        `email` would silently miss a match on `email2`/`email3`.

        `email` should already be normalized (see `normalized_email`); this path filters
        with the string as given.
        """
        fields = EMAIL_FIELDS[search_type]
        sparse = PARTY_SPARSE_FIELDS[search_type]
        documents = await asyncio.gather(
            *(
                self._client.get(
                    f"/{search_type}",
                    params={
                        f"filter[{field}][eq]": email,
                        f"fields[{search_type}]": sparse,
                    },
                    schema=PartyCollectionDocument,
                )
                for field in fields
            )
        )
        return self._merge_candidates(documents, search_type=search_type)

    async def _quick_search(
        self,
        *,
        search_type: SearchType,
        search: str,
        options: QuickSearchOptionsDto | None,
    ) -> tuple[PartyCandidate, ...]:
        """Fuzzy/name lookup via `GET /quick-search`, pinned to a single `search_type`.

        Prefix-anchored: `Dispersion` misses `Capstone Dispersion`; `Capstone Disp` hits.
        Never sends Backstop's `EMAIL_ADDRESS` search type: email-looking input is routed
        to `_search_by_email` before reaching here.
        """
        resolved_options = options if options is not None else QuickSearchOptionsDto()
        response = await self._client.get(
            "/quick-search",
            params=self._quick_search_params(
                search_type=search_type,
                search=search,
                options=resolved_options,
            ),
            schema=PartyCollectionDocument,
        )
        return candidates_from_document(response, search_type=search_type)

    def _quick_search_params(
        self,
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

    async def _search_by_like(
        self, *, search_type: SearchType, search: str
    ) -> tuple[PartyCandidate, ...]:
        """Substring lookup via `filter[<field>][like]` when `/quick-search` returns nothing.

        `/quick-search` is prefix-anchored. One page of 200 is enough: more hits is already
        ambiguous.
        """
        field = _LIKE_FIELDS.get(search_type)
        if field is None:
            return ()
        page = await self._client.paginate(
            f"/{search_type}",
            schema=_PartyResource,
            params={
                f"filter[{field}][like]": search,
                f"fields[{search_type}]": PARTY_SPARSE_FIELDS[search_type],
            },
            page_size=200,
            max_records=200,
        )
        return candidates_from_resources(page.items, search_type=search_type)

    def _merge_candidates(
        self, documents: Sequence[PartyCollectionDocument], *, search_type: SearchType
    ) -> tuple[PartyCandidate, ...]:
        by_id: dict[str, PartyCandidate] = {}
        for document in documents:
            for candidate in candidates_from_document(document, search_type=search_type):
                by_id.setdefault(candidate.key, candidate)
        return tuple(by_id.values())
