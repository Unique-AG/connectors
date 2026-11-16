"""Atlassian Rovo MCP v2 (hosted, closed source).

Writes go only to a throwaway child page of the research page in the PLATFORM space. Rovo v2 has
no operation that deletes a page, so cleanup and `sweep` use the Confluence REST API and need
ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN in `probe/.env`
(token: https://id.atlassian.com/manage-profile/security/api-tokens).

The destructive calls are ones that cannot hurt a page nobody else has seen: unwatching it and
clearing its (empty) content-level permission grants.
"""

import base64
import os
from typing import Any

import httpx2

from probe import Leftover, Probe, Target

SITE = "https://unique-ch.atlassian.net"
SPACE_KEY = "ptf"
PARENT_PAGE_ID = "2919235590"

TARGET = Target(name="atlassian", url="https://mcp.atlassian.com/v2/mcp", auth="oauth")


def _basic_auth() -> str:
    email, token = os.environ.get("ATLASSIAN_EMAIL"), os.environ.get("ATLASSIAN_API_TOKEN")
    assert email and token, "set ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN in probe/.env so cleanup can delete pages"
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def _rest() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(base_url=SITE, headers={"Authorization": _basic_auth()}, timeout=30)


async def _delete_page(page_id: str) -> None:
    async with _rest() as rest:
        response = await rest.delete(f"/wiki/api/v2/pages/{page_id}")
        assert response.status_code in (204, 404), f"delete page {page_id}: {response.status_code} {response.text}"
        # Purging empties the trash too; it needs space-admin rights, so a refusal is tolerated.
        await rest.delete(f"/wiki/api/v2/pages/{page_id}", params={"purge": "true"})


def _find(data: Any, key: str) -> Any:
    """First value under `key` anywhere in a JSON tree; Rovo nests ids differently per operation."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        values = data.values()
    elif isinstance(data, list):
        values = data
    else:
        return None
    for value in values:
        found = _find(value, key)
        if found is not None:
            return found
    return None


async def scenario(probe: Probe) -> None:
    _basic_auth()  # fail before writing anything when cleanup is impossible

    await probe.call("getAccessibleAtlassianResources", {})
    await probe.call(
        "searchJiraIssuesUsingJql", {"cloudId": SITE, "jql": "created >= -7d ORDER BY created DESC", "maxResults": 1}
    )

    created = await probe.call(
        "createConfluenceContent",
        {
            "cloudId": SITE,
            "parent": {"parentContentId": PARENT_PAGE_ID},
            "contentType": "page",
            "title": probe.name("page"),
            "body": {
                "format": "markdown",
                "value": "Throwaway page from the MCP elicitation probe; deleted after the run.",
            },
        },
    )
    page_id = _find(created.json_body(), "id") or _find(created.json_body(), "contentId")
    if page_id is None:
        return
    page_id = str(page_id)
    probe.on_cleanup(f"page {page_id}", lambda: _delete_page(page_id))

    current = await probe.call(
        "getConfluenceContent", {"cloudId": SITE, "content_id": page_id, "draft": True, "detail": "full"}
    )
    await probe.call(
        "updateConfluenceContent",
        {
            "cloudId": SITE,
            "contentId": page_id,
            "snapshotToken": _find(current.json_body(), "snapshotToken"),
            "body": {"format": "markdown", "value": "Updated by the MCP elicitation probe."},
        },
    )
    page = {"cloudId": SITE, "inputs": {"cloudId": SITE, "contentId": page_id}}
    await probe.call("executeWrite", {"name": "watchConfluenceContent", **page})
    await probe.call("executeDestructive", {"name": "unwatchConfluenceContent", **page})
    await probe.call("executeDestructive", {"name": "removeConfluenceContentPermissions", **page})


async def find_leftovers(probe: Probe, prefix: str) -> list[Leftover]:
    async with _rest() as rest:
        response = await rest.get(
            "/wiki/rest/api/search",
            params={"cql": f'space = "{SPACE_KEY}" AND type = page AND title ~ "{prefix}"', "limit": 100},
        )
    response.raise_for_status()
    return [
        Leftover(kind="page", id=r["content"]["id"], title=r["content"]["title"])
        for r in response.json().get("results", [])
        if r["content"]["title"].startswith(prefix)
    ]


async def delete_leftover(probe: Probe, leftover: Leftover) -> None:
    await _delete_page(leftover.id)
