import asyncio
from typing import ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import TypeAdapter

from world_check_mcp.persistence import Cache
from world_check_mcp.upstream import CaseTemplateResponse
from world_check_mcp.upstream import GET_CASE_TEMPLATE_FOR_GROUP
from world_check_mcp.upstream import GET_COUNTRIES
from world_check_mcp.upstream import GET_NATIONALITIES
from world_check_mcp.upstream import GetCaseTemplateForGroupPath
from world_check_mcp.upstream import GetCaseTemplateForGroupRequest
from world_check_mcp.upstream import GetCountriesRequest
from world_check_mcp.upstream import GetNationalitiesRequest
from world_check_mcp.upstream import Upstream
from world_check_mcp.upstream import UpstreamError

STATIC_SECONDS = 24 * 60 * 60
_TEMPLATE_SECONDS = 300
_NAMES = TypeAdapter(dict[str, str])
_TEMPLATE = TypeAdapter(CaseTemplateResponse)


class ScreeningLookups(BaseModel):
    """What a screening reads from LSEG before it saves a case."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    template: CaseTemplateResponse
    countries: dict[str, str]
    nationalities: dict[str, str]


async def countries(*, upstream: Upstream, cache: Cache) -> dict[str, str]:
    async def load() -> dict[str, str]:
        return (await upstream.call(GET_COUNTRIES, GetCountriesRequest())).root

    return await cache.read_through(
        key="countries", adapter=_NAMES, ttl_seconds=STATIC_SECONDS, load=load
    )


async def nationalities(*, upstream: Upstream, cache: Cache) -> dict[str, str]:
    async def load() -> dict[str, str]:
        return (await upstream.call(GET_NATIONALITIES, GetNationalitiesRequest())).root

    return await cache.read_through(
        key="nationalities", adapter=_NAMES, ttl_seconds=STATIC_SECONDS, load=load
    )


async def case_template(*, upstream: Upstream, cache: Cache, group_id: str) -> CaseTemplateResponse:
    async def load() -> CaseTemplateResponse:
        return await upstream.call(
            GET_CASE_TEMPLATE_FOR_GROUP,
            GetCaseTemplateForGroupRequest(path=GetCaseTemplateForGroupPath(group_id=group_id)),
        )

    return await cache.read_through(
        key=_template_key(group_id=group_id),
        adapter=_TEMPLATE,
        ttl_seconds=_TEMPLATE_SECONDS,
        load=load,
    )


async def screening_lookups(*, upstream: Upstream, cache: Cache, group_id: str) -> ScreeningLookups:
    template, country_names, nationality_names = await asyncio.gather(
        case_template(upstream=upstream, cache=cache, group_id=group_id),
        countries(upstream=upstream, cache=cache),
        nationalities(upstream=upstream, cache=cache),
    )
    return ScreeningLookups(
        template=template, countries=country_names, nationalities=nationality_names
    )


async def forget_template_if_rejected(*, cache: Cache, group_id: str, error: UpstreamError) -> None:
    """A rejected save may mean the template changed under the cache. The save is not retried,
    so the next screening reads the template again.
    """
    status = error.status_code
    if status is not None and 400 <= status < 500:
        await cache.forget(_template_key(group_id=group_id))


def _template_key(*, group_id: str) -> str:
    return f"case-template:{group_id}"
