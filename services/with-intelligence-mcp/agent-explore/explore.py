#!/usr/bin/env python3
"""GET-only CLI for the live With Intelligence v3 API. Loads .env from this directory.

    uv run agent-explore/explore.py /v3/investors -p 'name=Virginia Retirement System'
    uv run agent-explore/explore.py /v3/investors/2504
    uv run agent-explore/explore.py /v3/mandates -p investor_id=2504 -p asset_class_group=hfm

Run it through `uv run` from the service root, for the same reason as `spec.py`.

Signs in once with the username and password from `.env`, caches the access token next to the
probe cache, and refreshes it when it expires (1 hour). Responses are cached under
`.probe-cache/` keyed by path and query, so re-running a probe costs nothing and a recorded body
can become a test fixture.

GET only, deliberately: the only POSTs this file will ever make are to `/v3/auth/sign-in` and
`/v3/auth/refresh`. Everything else about the account — its password, its permissions — is
changed by a human on the vendor's site, not from here.

Read `.claude/skills/with-intelligence-api/SKILL.md` first, and `./spec.py` for shapes; this is
for the behaviour a spec cannot tell you.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import cast

import httpx
from dotenv import load_dotenv
from pydantic import TypeAdapter, ValidationError

_HERE = Path(__file__).resolve().parent
_CACHE = _HERE / ".probe-cache"
_TOKEN_FILE = _CACHE / "token.json"

# The vendor's access token lives an hour. Re-signing in a minute early costs one request and
# avoids a 401 on a long probing session.
_TOKEN_TTL_SECONDS = 3600 - 60


class _Args(argparse.Namespace):
    path: str
    param: list[str]
    refresh: bool

    def __init__(self) -> None:
        super().__init__()
        self.path = ""
        self.param = []
        self.refresh = False


def _sign_in(base_url: str, username: str, password: str) -> str:
    """`POST /v3/auth/sign-in` → access token.

    Username and password only: no one-time passcode is part of this exchange. The passcode in
    the vendor's onboarding mail is the initial password for `POST /v3/auth/set-password`, done
    once by a human before any of this works.
    """
    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        response = client.post(
            "/v3/auth/sign-in", json={"username": username, "password": password}
        )
    if response.status_code != 200:
        raise SystemExit(
            f"sign-in failed with {response.status_code}. Check the credentials in .env; "
            + "a fresh account must set its password on the vendor's site first."
        )
    body = cast(dict[str, object], response.json())
    token = body.get("accessToken")
    if not isinstance(token, str):
        raise SystemExit(f"sign-in returned no accessToken (keys: {sorted(body)})")
    return token


def _access_token(base_url: str, username: str, password: str, refresh: bool) -> str:
    """A usable access token, from the cache when it is still fresh."""
    if _TOKEN_FILE.exists() and not refresh:
        cached = cast(dict[str, object], json.loads(_TOKEN_FILE.read_text()))
        issued_at = cached.get("issued_at")
        token = cached.get("access_token")
        if (
            isinstance(issued_at, (int, float))
            and isinstance(token, str)
            and time.time() - issued_at < _TOKEN_TTL_SECONDS
        ):
            return token

    token = _sign_in(base_url, username, password)
    _TOKEN_FILE.write_text(json.dumps({"access_token": token, "issued_at": time.time()}))
    return token


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is not set — copy .env.example to .env and fill it in")
    return value


def main() -> None:
    load_dotenv(_HERE / ".env")
    base_url = os.environ.get("WITH_INTELLIGENCE_BASE_URL", "https://api.withintelligence.com")
    username = _required_env("WITH_INTELLIGENCE_USERNAME")
    password = _required_env("WITH_INTELLIGENCE_PASSWORD")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="e.g. /v3/investors or /v3/investors/2504")
    parser.add_argument("-p", "--param", action="append", default=[], help="key=value")
    parser.add_argument("--refresh", action="store_true", help="ignore the cached response")
    args = parser.parse_args(namespace=_Args())
    params = dict(p.split("=", 1) for p in args.param)

    _CACHE.mkdir(exist_ok=True)
    key = hashlib.sha256(
        json.dumps(
            {"base_url": base_url, "path": args.path, "query": params}, sort_keys=True
        ).encode()
    ).hexdigest()[:16]
    cache_file = _CACHE / f"{key}.json"
    if cache_file.exists() and not args.refresh:
        print(cache_file.read_text())
        return

    token = _access_token(base_url, username, password, args.refresh)
    headers = {"authorization": f"Bearer {token}", "accept": "application/json"}
    with httpx.Client(base_url=base_url, headers=headers, timeout=120.0) as client:
        try:
            response = client.get(args.path, params=params)
        except httpx.TimeoutException:
            raise SystemExit(
                "With Intelligence did not respond within 2 minutes; treat the API as down."
            ) from None
        if response.status_code == 401:
            # The cached token outlived its hour, or the account's session was invalidated.
            token = _access_token(base_url, username, password, refresh=True)
            client.headers["authorization"] = f"Bearer {token}"
            response = client.get(args.path, params=params)

    try:
        body: object = TypeAdapter(object).validate_json(response.content)
    except ValidationError:
        body = response.text
    record: dict[str, object] = {
        "path": args.path,
        "query": params,
        "status": response.status_code,
        "body": body,
    }
    out = json.dumps(record, indent=2)
    cache_file.write_text(out)
    print(out)


if __name__ == "__main__":
    main()
