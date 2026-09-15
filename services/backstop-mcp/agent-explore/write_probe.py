#!/usr/bin/env python3
"""Write-method CLI for the live Backstop REST API. Not part of the shipped MCP server.

Companion to the GET-only `explore.py`. Only run this against an instance the user has
explicitly declared writable for the task, and delete every record it creates.

Loads `.env` from this directory. Appends each response to `.probe-cache/` (gitignored).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import TypeAdapter, ValidationError


class _Args(argparse.Namespace):
    method: str
    path: str
    body: str | None
    label: str

    def __init__(self) -> None:
        super().__init__()
        self.method = ""
        self.path = ""
        self.body = None
        self.label = ""


def main() -> None:
    here = Path(__file__).resolve().parent
    load_dotenv(here / ".env")
    base_url = os.environ["BACKSTOP_BASE_URL"]
    username = os.environ["BACKSTOP_SERVICE_USERNAME"]
    token = os.environ["BACKSTOP_SERVICE_API_TOKEN"]
    auth = base64.b64encode(f"{username}:{token}".encode()).decode()
    headers = {
        "authorization": f"Basic {auth}",
        "token": "true",
        "accept": "application/vnd.api+json",
        "content-type": "application/vnd.api+json",
    }

    parser = argparse.ArgumentParser()
    parser.add_argument("method", choices=["POST", "PATCH", "DELETE"])
    parser.add_argument("path")
    parser.add_argument("-b", "--body", default=None)
    parser.add_argument("-l", "--label", default="write")
    args = parser.parse_args(namespace=_Args())

    content = args.body.encode() if args.body is not None else None

    with httpx.Client(base_url=base_url, headers=headers, timeout=120.0) as client:
        try:
            resp = client.request(args.method, args.path, content=content)
        except httpx.TimeoutException:
            raise SystemExit(
                "Backstop API did not respond within 2 minutes; treat the API as down."
            ) from None

    try:
        body: object = TypeAdapter(object).validate_json(resp.content)
    except ValidationError:
        body = resp.text

    record = {
        "method": args.method,
        "path": args.path,
        "request_body": args.body,
        "status": resp.status_code,
        "body": body,
    }
    out = json.dumps(record, indent=2)

    cache_dir = here / ".probe-cache"
    cache_dir.mkdir(exist_ok=True)
    (cache_dir / f"w-{int(time.time())}-{args.label}.json").write_text(out)
    print(out)


if __name__ == "__main__":
    main()
