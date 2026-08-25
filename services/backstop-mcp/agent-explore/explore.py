#!/usr/bin/env python3
"""GET-only CLI for the live Backstop REST API. Loads .env from this directory."""

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


def main() -> None:
    here = Path(__file__).resolve().parent
    load_dotenv(here / ".env")
    base_url = os.environ["BACKSTOP_BASE_URL"]
    username = os.environ["BACKSTOP_SERVICE_USERNAME"]
    token = os.environ["BACKSTOP_SERVICE_API_TOKEN"]
    auth = base64.b64encode(f"{username}:{token}".encode()).decode()
    headers = {"authorization": f"Basic {auth}", "token": "true"}

    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("-p", "--param", action="append", default=[])
    args = parser.parse_args(namespace=_Args())
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
