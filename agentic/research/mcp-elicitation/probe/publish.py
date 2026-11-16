"""Publish REPORT.md and the findings to the research page in Confluence through Rovo MCP.

    uv run publish.py

Category child pages are created once and updated on later runs; the main page is replaced.
"""

import asyncio
import json
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import markdown

from probe import RUNS_DIR, Probe, Recorder, connect
from targets.atlassian import PARENT_PAGE_ID, SITE, TARGET

RESEARCH_DIR = Path(__file__).parent.parent
TITLE_PREFIX = "MCP elicitation research"

CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "collaboration": (
        "Collaboration servers",
        [
            "atlassian-rovo",
            "atlassian-sooperset",
            "slack-korotovsky",
            "ms365-softeria",
            "notion-official",
            "google-workspace-taylorwilsdon",
            "nextcloud",
        ],
    ),
    "payments": ("Payments and trading servers", ["stripe", "paypal", "alpaca", "square", "adyen", "coinbase"]),
    "fintech": (
        "Fintech data, accounting and enterprise data servers",
        ["monarch", "xero", "quickbooks", "polygon", "financial-datasets", "salesforce-dx", "snowflake-labs"],
    ),
    "platform": (
        "Cloud and developer platform servers",
        ["github", "azure-mcp", "aws-labs", "azure-devops", "hubspot", "supabase", "sentry", "cloudflare", "grafana"],
    ),
    "other": ("Other servers", ["kubernetes", "context7", "perforce", "home-assistant", "semgrep"]),
    "docs": (
        "Vendor documentation for hosted servers",
        [
            "slack-official",
            "ms365-microsoft",
            "notion-hosted",
            "linear",
            "asana",
            "box",
            "github-hosted",
            "stripe-hosted",
            "paypal-hosted",
            "plaid",
            "ramp",
            "brex",
            "factset",
            "lseg",
            "sp-global",
            "moodys",
            "morningstar",
            "pitchbook",
            "quartr",
            "hubspot-hosted",
            "salesforce-hosted",
            "snowflake-managed",
            "azure-devops-hosted",
            "sentry-hosted",
            "supabase-hosted",
        ],
    ),
}


def category_body(slugs: list[str]) -> str:
    intro = "One section per server, in the format of the parent page. Evidence links point at the exact commit reviewed.\n\n"
    sections = []
    for slug in slugs:
        text = (RESEARCH_DIR / "findings" / f"{slug}.md").read_text()
        sections.append(re.sub(r"^(#+) ", lambda m: "#" + m.group(1) + " ", text, flags=re.MULTILINE))
    return intro + "\n\n---\n\n".join(sections)


def body_json(outcome: Any) -> Any:
    body = outcome.json_body()
    assert not outcome.is_error and body is not None, f"{outcome.tool} failed: {outcome.text[:1000]}"
    assert find(body, "ok") is not False, f"{outcome.tool} refused: {outcome.text[:1000]}"
    return body


def find(data: Any, key: str) -> Any:
    if isinstance(data, dict):
        if key in data:
            return data[key]
        children = list(data.values())
    elif isinstance(data, list):
        children = data
    else:
        return None
    return next((v for v in (find(c, key) for c in children) if v is not None), None)


async def upsert(probe: Probe, title: str, markdown_body: str, existing_id: str | None) -> str:
    if existing_id is None:
        created = body_json(
            await probe.call(
                "createConfluenceContent",
                {
                    "cloudId": SITE,
                    "parent": {"parentContentId": PARENT_PAGE_ID},
                    "contentType": "page",
                    "title": title,
                    "body": {"format": "markdown", "value": markdown_body},
                },
            )
        )
        return str(find(created, "id"))
    await replace(probe, existing_id, {"format": "markdown", "value": markdown_body})
    return existing_id


async def replace(probe: Probe, content_id: str, body: dict[str, str]) -> None:
    current = body_json(
        await probe.call(
            "getConfluenceContent", {"cloudId": SITE, "content_id": content_id, "draft": True, "detail": "full"}
        )
    )
    body_json(
        await probe.call(
            "updateConfluenceContent",
            {
                "cloudId": SITE,
                "contentId": content_id,
                "snapshotToken": find(current, "snapshotToken"),
                "body": body,
            },
        )
    )


async def main() -> None:
    recorder = Recorder(RUNS_DIR / "publish.jsonl")
    probe_ref: list[Probe] = []
    async with AsyncExitStack() as stack:
        client = await connect(stack, TARGET, recorder, probe_ref, elicitation=True, mode="auto")
        probe = Probe(client, recorder, "publish", "decline")
        probe_ref.append(probe)

        children = body_json(
            await probe.call(
                "searchConfluence",
                {"cloudId": SITE, "cql": f'parent = {PARENT_PAGE_ID} AND title ~ "{TITLE_PREFIX}"'},
            )
        )
        existing = {
            (r.get("content") or r)["title"]: str((r.get("content") or r)["id"])
            for r in find(children, "results") or []
        }

        links = {}
        for key, (heading, slugs) in CATEGORIES.items():
            title = f"{TITLE_PREFIX}: {heading}"
            page_id = await upsert(probe, title, category_body(slugs), existing.get(title))
            links[key] = f"[details](https://unique-ch.atlassian.net/wiki/spaces/ptf/pages/{page_id})"

        report = (RESEARCH_DIR / "REPORT.md").read_text()
        for key, link in links.items():
            report = report.replace("{{" + key + "}}", link)
        assert "{{" not in report, "unresolved placeholder in REPORT.md"
        # Confluence turns the child-page links into smart links, and Rovo refuses to replace those with markdown.
        html = markdown.markdown(report, extensions=["tables"])
        await replace(probe, PARENT_PAGE_ID, {"format": "html", "value": html})
    print(json.dumps(links, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
