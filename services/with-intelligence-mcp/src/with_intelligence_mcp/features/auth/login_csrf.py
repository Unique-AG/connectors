"""Double-submit CSRF protection for the hosted With Intelligence login form.

`POST /login` takes a username and password and, on success, mints an
authorization code — so a cross-site POST that a victim could be tricked into submitting is
worth preventing. A token is minted when the form is rendered and sent two ways: as a cookie
and as a hidden form field. The POST handler requires them to match.

Two independent things then have to hold for a forged submission to work, and neither does:
`SameSite=Lax` means the browser does not attach the cookie to a cross-site POST at all, and an
attacker who can't read the cookie can't put its value in the form. `HttpOnly` keeps script on
any same-site page from lifting it.

The cookie name is derived from the `request_id` so two logins running in the same browser (two
MCP clients connecting at once) don't clobber each other's token — a single fixed name would
mean the second form rendered invalidates the first, and the user sees a spurious failure.

No database column: the token only needs to prove "the same browser that was shown this form is
submitting it", which a signed-nowhere, compare-both-copies check already gives. What it
deliberately does *not* try to prove is which With Intelligence account the browser belongs to — see
`provider.handle_login_get` for the headers that keep the `request_id` itself from leaking.
"""

import hashlib
import hmac
import secrets

from starlette.requests import Request
from starlette.responses import Response

_COOKIE_PREFIX = "wi_login_csrf_"
_TOKEN_BYTES = 32
# Cookie names must be HTTP tokens, so the request_id is hashed rather than embedded: it is
# URL-safe base64 and would otherwise need escaping, and the digest keeps the name fixed-length.
_NAME_DIGEST_CHARS = 16


def csrf_cookie_name(request_id: str) -> str:
    """The cookie name carrying the CSRF token for one pending authorization."""
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:_NAME_DIGEST_CHARS]
    return f"{_COOKIE_PREFIX}{digest}"


def issue_csrf_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def set_csrf_cookie(
    response: Response,
    request_id: str,
    token: str,
    *,
    path: str,
    max_age_seconds: int,
    secure: bool,
) -> None:
    """Attach the CSRF cookie to a rendered login form.

    `secure` is driven by the configured public base URL rather than hardcoded, so a local
    http:// development deploy still gets a working form; every real deploy is https and so gets
    the flag. `path` is scoped to the login endpoint so the cookie is never sent anywhere else.
    """
    response.set_cookie(
        csrf_cookie_name(request_id),
        token,
        max_age=max_age_seconds,
        path=path,
        httponly=True,
        secure=secure,
        samesite="lax",
    )


def clear_csrf_cookie(response: Response, request_id: str, *, path: str, secure: bool) -> None:
    """Drop the cookie once its pending authorization has been consumed.

    `secure` / `httponly` / `samesite` must match `set_csrf_cookie`: browsers treat a clear
    with different flags as a different cookie and leave the original in place.
    """
    response.delete_cookie(
        csrf_cookie_name(request_id),
        path=path,
        secure=secure,
        httponly=True,
        samesite="lax",
    )


def csrf_token_is_valid(request: Request, request_id: str, submitted: str) -> bool:
    """Whether the submitted form token matches the cookie for this `request_id`.

    Fails closed on a missing cookie or a missing form value: absence is exactly what a
    cross-site POST looks like. `compare_digest` rather than `==` so the check can't be turned
    into a way to read the cookie a character at a time.
    """
    cookie = request.cookies.get(csrf_cookie_name(request_id))
    if not cookie or not submitted:
        return False
    return hmac.compare_digest(cookie, submitted)
