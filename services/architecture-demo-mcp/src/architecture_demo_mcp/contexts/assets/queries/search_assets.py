from pydantic import BaseModel

from architecture_demo_mcp.upstream import SEARCH_ASSETS
from architecture_demo_mcp.upstream import Upstream


async def search_assets(*, upstream: Upstream, query: str, limit: int) -> list[AssetMatch]:
    results = await upstream.call(SEARCH_ASSETS, query=query, limit=limit)
    return [
        AssetMatch(
            ticker=result.ticker,
            name=result.name,
            asset_type=result.assetType,
            is_active=result.isActive,
        )
        for result in results
        if result.ticker is not None
    ]


class AssetMatch(BaseModel):
    ticker: str
    name: str | None
    asset_type: str | None
    is_active: bool | None
