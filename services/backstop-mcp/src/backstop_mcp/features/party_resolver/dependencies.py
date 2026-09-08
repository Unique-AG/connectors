from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.party_resolver.queries import GetPartyNameQuery, ResolvePartyQuery


@lru_cache(maxsize=1)
def get_party_name_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> GetPartyNameQuery:
    return GetPartyNameQuery(client=client)


@lru_cache(maxsize=1)
def get_resolve_party_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    get_party_name_query: GetPartyNameQuery = Depends(get_party_name_query_factory),
) -> ResolvePartyQuery:
    return ResolvePartyQuery(client=client, get_party_name_query=get_party_name_query)
