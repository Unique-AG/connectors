#!/usr/bin/env python3
"""POST-capable probe for Backstop's UI activity-search endpoints. Scratch, not shipped.

Separate from `explore.py` on purpose. `explore.py` is GET-only against whatever
`BACKSTOP_BASE_URL` says; this script POSTs, so the two authorized tenants are **hardcoded** below and asserted
before every request. It cannot be pointed at another tenant by editing `.env`.

Authorized scope: POST search bodies only (`/entity-activities`, `/entity-activities-filters`,
`/activity-search`). These are POST-as-query endpoints — the swagger calls them "Create a new ..."
but they return result sets. Do not send create/update/delete payloads.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# Hardcoded per explicit authorization: POST is permitted against these two tenants only,
# and `--tenant` must name one of them, so the target is always explicit at the call site.
TENANTS = {
    "fb-rm-lg-26": "https://fb-rm-lg-26.backstopsolutions.com/backstop/api",
    "capstoneco": "https://capstoneco.backstopsolutions.com/backstop/api",
}
ALLOWED_PATHS = frozenset(
    {"/entity-activities", "/entity-activities-filters", "/activity-search"}
)

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT.parent.parent / "docs" / "json"
MANIFEST = CACHE_DIR / "manifest.jsonl"


class _Args(argparse.Namespace):
    path: str = ""
    body: str = ""
    note: str = ""
    tenant: str = ""


def _slug(path: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", path.strip("/")).strip("-").lower()
    return cleaned[:80] or "root"


def _next_seq() -> int:
    existing = [p for p in CACHE_DIR.glob("*.json") if p.name[:3].isdigit()]
    return max((int(p.name[:3]) for p in existing), default=0) + 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="one of: " + ", ".join(sorted(ALLOWED_PATHS)))
    parser.add_argument("--body", required=True, help="JSON request body")
    parser.add_argument(
        "--tenant", required=True, choices=sorted(TENANTS), help="which authorized tenant to POST to"
    )
    parser.add_argument("--note", default="", help="stored on the cache record")
    args = parser.parse_args(namespace=_Args())

    assert args.path in ALLOWED_PATHS, f"{args.path} is not an authorized search endpoint"
    base_url = TENANTS[args.tenant]
    allowed_host = httpx.URL(base_url).host
    assert allowed_host is not None and args.tenant in allowed_host, "tenant guard"
    payload: object = json.loads(args.body)

    load_dotenv(ROOT / ".env")
    username = os.environ["BACKSTOP_SERVICE_USERNAME"]
    token = os.environ["BACKSTOP_SERVICE_API_TOKEN"]
    auth = base64.b64encode(f"{username}:{token}".encode()).decode()
    headers = {
        "authorization": f"Basic {auth}",
        "token": "true",
        "accept": "application/vnd.api+json",
        "content-type": "application/vnd.api+json",
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=base_url, headers=headers, timeout=120.0) as client:
        assert client.build_request("POST", args.path).url.host == allowed_host, "tenant guard"
        try:
            resp = client.post(args.path, json=payload)
        except httpx.TimeoutException:
            raise SystemExit(
                "Backstop API did not respond within 2 minutes; treat the API as down."
            )
    try:
        body: object = resp.json()
    except Exception:
        body = {"_text": resp.text[:4000]}

    record: dict[str, Any] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "method": "POST",
        "tenant": allowed_host,
        "path": args.path,
        "request_body": payload,
        "status": resp.status_code,
        "note": args.note,
        "body": body,
    }
    filename = f"{_next_seq():03d}-post-{args.tenant}-{_slug(args.path)}-{resp.status_code}.json"
    (CACHE_DIR / filename).write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    with MANIFEST.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "file": filename,
                    "method": "POST",
                    "tenant": allowed_host,
                    "path": args.path,
                    "status": resp.status_code,
                    "note": args.note,
                },
                default=str,
            )
            + "\n"
        )
    print(f"{resp.status_code} POST {args.tenant}{args.path} -> {filename}")
    print(json.dumps(body, indent=2, default=str)[:3000])


if __name__ == "__main__":
    main()
