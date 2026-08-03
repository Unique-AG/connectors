import asyncio
from collections.abc import Mapping, Sequence

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.backstop_client.json_api import BackstopApiDocument, BackstopApiResource
from backstop_mcp.party_resolver.email import looks_like_email
from backstop_mcp.party_resolver.types import (
    PartyAttributes,
    PartyCandidate,
    QuickSearchOptions,
    SearchType,
)

# Plain assignments (not `type` statements) — `schema=` needs a real class object, and a PEP 695
# type alias isn't assignable to `type[T]` even though it resolves to one at runtime.
_PartyDocument = BackstopApiDocument[PartyAttributes]
_PartyResource = BackstopApiResource[PartyAttributes]

_EMAIL_FIELDS: Mapping[SearchType, tuple[str, ...]] = {
    "organizations": ("email",),
    "contacts": ("email",),
    "people": ("email", "email2", "email3"),
    "employees": ("email", "email2", "email3"),
}


async def search_by_email(
    client: BackstopClient,
    *,
    search_type: SearchType,
    email: str,
) -> tuple[PartyCandidate, ...]:
    """Exact-match email lookup across the email fields applicable to `search_type`.

    Queries each field separately (never AND-ed) and dedupes hits by resource id.
    """
    fields = _EMAIL_FIELDS[search_type]
    responses = await asyncio.gather(
        *(
            client.get(
                f"/{search_type}",
                params={f"filter[{field}][eq]": email},
                schema=_PartyDocument,
            )
            for field in fields
        )
    )
    return _merge_candidates(responses)


async def quick_search(
    client: BackstopClient,
    *,
    search_type: SearchType,
    search: str,
    options: QuickSearchOptions | None = None,
) -> tuple[PartyCandidate, ...]:
    """Fuzzy/name lookup via `GET /quick-search`, pinned to a single `search_type`."""
    resolved_options = options if options is not None else QuickSearchOptions()
    response = await client.get(
        "/quick-search",
        params=_quick_search_params(
            search_type=search_type,
            search=search,
            options=resolved_options,
        ),
        schema=_PartyDocument,
    )
    return _candidates_from_document(response)


def _quick_search_params(
    *,
    search_type: SearchType,
    search: str,
    options: QuickSearchOptions,
) -> dict[str, object]:
    assert options.limit > 0, "QuickSearchOptions.limit must be positive"

    params: dict[str, object] = {
        "filter[searchText][eq]": search,
        "filter[searchTypes][eq]": search_type,
        "filter[limit][eq]": options.limit,
        "filter[showAll][eq]": _bool_param(options.show_all),
        "filter[enhanceSearchTypes][eq]": _bool_param(options.enhance_search_types),
        "page[limit]": options.limit,
        "page[offset]": 0,
    }

    if options.full_email_match is None:
        if looks_like_email(search):
            params["filter[fullEmailMatch][eq]"] = "true"
    else:
        params["filter[fullEmailMatch][eq]"] = _bool_param(options.full_email_match)

    if options.filter_type is not None:
        params["filter[filterType][eq]"] = options.filter_type

    return params


def _bool_param(value: bool) -> str:
    return "true" if value else "false"


def _merge_candidates(documents: Sequence[_PartyDocument]) -> tuple[PartyCandidate, ...]:
    seen_ids: set[str] = set()
    merged: list[PartyCandidate] = []
    for document in documents:
        for candidate in _candidates_from_document(document):
            if candidate.id in seen_ids:
                continue
            seen_ids.add(candidate.id)
            merged.append(candidate)
    return tuple(merged)


def _candidates_from_document(document: _PartyDocument) -> tuple[PartyCandidate, ...]:
    data = document.data
    if data is None:
        resources: list[_PartyResource] = []
    elif isinstance(data, list):
        resources = data
    else:
        resources = [data]
    return tuple(_candidate_from_resource(resource) for resource in resources)


def _candidate_from_resource(resource: _PartyResource) -> PartyCandidate:
    # `resource.id` is already stripped and guaranteed non-blank by `BackstopApiResource`'s
    # schema validation; a blank `type` still falls back to "resource" here since that's a
    # caller-side display concern, not a structural defect the schema should reject.
    resource_type = resource.type or "resource"
    name = _display_name(resource.attributes)
    label = name if name is not None else f"{resource_type} #{resource.id}"
    return PartyCandidate(id=resource.id, name=name, label=label)


def _display_name(attributes: PartyAttributes) -> str | None:
    if attributes.name:
        return attributes.name

    composed = " ".join(part for part in (attributes.first_name, attributes.last_name) if part)
    return composed or None
