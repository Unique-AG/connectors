"""Print a delegated Graph access token for one test user, using the device-code flow.

Usage: get_token.py [expected-upn]

The sign-in prompt goes to stderr and the token goes to stdout only, so
`TOKEN=$(get_token.py <upn>)` keeps it out of the terminal.
Refresh tokens are cached in a mode-600 file outside the repository, so each user signs in once.
"""

import os
import sys
from pathlib import Path

import msal

SCOPES = [
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/Calendars.ReadWrite",
    "https://graph.microsoft.com/Contacts.ReadWrite",
    "https://graph.microsoft.com/Files.ReadWrite",
    "https://graph.microsoft.com/Files.Read.All",
    "https://graph.microsoft.com/Sites.Read.All",
    "https://graph.microsoft.com/User.Read",
]
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


def main() -> int:
    tenant = os.environ.get("ENTRA_TENANT_ID")
    client = os.environ.get("ENTRA_CLIENT_ID")
    expected = sys.argv[1].lower() if len(sys.argv) > 1 else None
    if not tenant or not client:
        print("Set ENTRA_TENANT_ID and ENTRA_CLIENT_ID first.", file=sys.stderr)
        return 2
    cache = load_cache()
    app = msal.PublicClientApplication(
        client, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=cache
    )
    accounts = [a for a in app.get_accounts() if not expected or a["username"].lower() == expected]
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
    if not result or "access_token" not in result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            print(f"Device flow failed: {flow.get('error')}", file=sys.stderr)
            return 1
        print(flow["message"], file=sys.stderr)
        result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        reason = str(result.get("error_description", "")).splitlines()[:1]
        print(f"Sign-in failed: {result.get('error')} {reason}", file=sys.stderr)
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
