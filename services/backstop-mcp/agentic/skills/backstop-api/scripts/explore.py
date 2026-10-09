#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "httpx==0.28.1",
#   "pydantic==2.13.5",
#   "python-dotenv==1.2.3",
# ]
# ///
"""GET-only CLI for the live Backstop REST API. Not part of the shipped MCP server.

Run from this skill's directory (the folder that contains SKILL.md):

    uv run scripts/explore.py /people -p "page[limit]=5"

Loads `.env` from this directory, or from services/backstop-mcp/agent-explore/.env when
this directory has none. Writes each response to `.probe-cache/` (gitignored).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import TypeAdapter, ValidationError


class _Args(argparse.Namespace):
    path: str
    param: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.path = ""
        self.param = []


def _env_file() -> Path:
    local = Path(__file__).resolve().parent / ".env"
    if local.is_file():
        return local
    for directory in local.parent.parents:
        candidate = directory / "services" / "backstop-mcp" / "agent-explore" / ".env"
        if candidate.is_file():
            return candidate
        sibling = directory / "agent-explore" / ".env"
        if sibling.is_file() and (directory / "pyproject.toml").is_file():
            return sibling
    return local


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GET one Backstop path and print the JSON response."
    )
    parser.add_argument("path", help="e.g. /people or /people/12345")
    parser.add_argument(
        "-p", "--param", action="append", default=[], help="key=value query parameter"
    )
    args = parser.parse_args(namespace=_Args())

    here = Path(__file__).resolve().parent
    load_dotenv(_env_file())
    missing = [
        name
        for name in (
            "BACKSTOP_BASE_URL",
            "BACKSTOP_SERVICE_USERNAME",
            "BACKSTOP_SERVICE_API_TOKEN",
        )
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit(
            "missing "
            + ", ".join(missing)
            + ". Copy scripts/.env.example to scripts/.env, or keep those values in "
            + "services/backstop-mcp/agent-explore/.env."
        )
    base_url = os.environ["BACKSTOP_BASE_URL"]
    username = os.environ["BACKSTOP_SERVICE_USERNAME"]
    token = os.environ["BACKSTOP_SERVICE_API_TOKEN"]
    auth = base64.b64encode(f"{username}:{token}".encode()).decode()
    headers = {"authorization": f"Basic {auth}", "token": "true"}

    params = dict(p.split("=", 1) for p in args.param)

    cache_dir = here / ".probe-cache"
    cache_dir.mkdir(exist_ok=True)
    key = hashlib.sha256(
        json.dumps(
            {"base_url": base_url, "path": args.path, "query": params},
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    cache_file = cache_dir / f"{key}.json"
    if cache_file.exists():
        print(cache_file.read_text())
        return

    with httpx.Client(base_url=base_url, headers=headers, timeout=120.0) as client:
        try:
            resp = client.get(args.path, params=params)
        except httpx.TimeoutException:
            raise SystemExit(
                "Backstop API did not respond within 2 minutes; treat the API as down."
            ) from None
    try:
        body: object = TypeAdapter(object).validate_json(resp.content)
    except ValidationError:
        body = resp.text
    record: dict[str, object] = {
        "path": args.path,
        "query": params,
        "status": resp.status_code,
        "body": body,
    }
    out = json.dumps(record, indent=2)
    cache_file.write_text(out)
    print(out)


if __name__ == "__main__":
    main()
