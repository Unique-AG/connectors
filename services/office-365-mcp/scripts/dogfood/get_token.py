"""Print a delegated Graph access token for one test user, using the device-code flow.

Usage: get_token.py [expected-upn] [--silent] [--scopes-for TOOL ...] [--scopes NAME ...]
       [--list-scopes]

The scopes are the union that the server needs for all its tools, plus the scopes that only the recorder needs.
--scopes-for asks for the scopes of the named tools only. --scopes adds Graph permissions by
name, such as Group.Read.All, to either set. --list-scopes prints the scopes and
makes no request. --silent never starts a device flow: it exits with 3 when the cached refresh
token is not enough.

The sign-in prompt goes to stderr and the token goes to stdout only, so
`TOKEN=$(get_token.py <upn>)` keeps it out of the terminal.
Refresh tokens are cached in a mode-600 file outside the repository, so each user signs in once.
"""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import msal

from office_365_mcp.tools import TOOL_NAMES, resolve

RECORDING_ONLY = (
    "https://graph.microsoft.com/User.ReadBasic.All",
    "https://graph.microsoft.com/Notes.ReadWrite.All",
    "https://graph.microsoft.com/Team.Create",
)
CACHE_PATH = Path(
    os.environ.get("DOGFOOD_TOKEN_CACHE", "~/.cache/dogfood-graph/msal.json")
).expanduser()


def load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if CACHE_PATH.is_file():
        cache.deserialize(CACHE_PATH.read_text(encoding="utf-8"))
    return cache


def save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(CACHE_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(cache.serialize())


def scopes_of(tools: Sequence[str], extra: Sequence[str] = ()) -> list[str]:
    selection = resolve(presets=None, enabled=tools or TOOL_NAMES)
    named = [f"https://graph.microsoft.com/{name}" for name in extra]
    return list(
        dict.fromkeys([*selection.graph_scopes, *([] if tools else RECORDING_ONLY), *named])
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upn", nargs="?")
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--list-scopes", action="store_true")
    parser.add_argument("--scopes-for", nargs="+", default=[], metavar="TOOL")
    parser.add_argument("--scopes", nargs="+", default=[], metavar="NAME")
    arguments = parser.parse_args(argv)
    scopes = scopes_of(arguments.scopes_for, arguments.scopes)
    if arguments.list_scopes:
        print("\n".join(scopes))
        return 0
    tenant = os.environ.get("ENTRA_TENANT_ID")
    client = os.environ.get("ENTRA_CLIENT_ID")
    expected = arguments.upn.lower() if arguments.upn else None
    if not tenant or not client:
        print("Set ENTRA_TENANT_ID and ENTRA_CLIENT_ID first.", file=sys.stderr)
        return 2
    cache = load_cache()
    app = msal.PublicClientApplication(
        client, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=cache
    )
    accounts = [a for a in app.get_accounts() if not expected or a["username"].lower() == expected]
    result = app.acquire_token_silent(scopes, account=accounts[0]) if accounts else None
    if (not result or "access_token" not in result) and arguments.silent:
        print("Silent sign-in failed; run record_all.sh login.", file=sys.stderr)
        return 3
    if not result or "access_token" not in result:
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            print(f"Device flow failed: {flow.get('error')}", file=sys.stderr)
            return 1
        print(flow["message"], file=sys.stderr)
        result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        reason = str(result.get("error_description", "")).splitlines()[:1]
        print(f"Sign-in failed: {result.get('error')} {reason}", file=sys.stderr)
        if any(code in str(reason) for code in ("AADSTS65001", "AADSTS90094")):
            consent = f"login.microsoftonline.com/{tenant}/adminconsent?client_id={client}"
            print(f"An admin must grant consent once: https://{consent}", file=sys.stderr)
            return 4
        return 1
    user = str(
        result.get("id_token_claims", {}).get("preferred_username") or accounts[0]["username"]
    )
    if expected and user.lower() != expected:
        print(f"Signed in as {user}, expected {expected}; token not issued.", file=sys.stderr)
        return 1
    save_cache(cache)
    print(f"Signed in as {user}", file=sys.stderr)
    print(result["access_token"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
